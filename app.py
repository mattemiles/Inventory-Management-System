"""CMT Asset Manager — local-only personal inventory. Python 3.11+."""
from __future__ import annotations
import csv, hashlib, hmac, io, json, os, re, secrets, shutil, sqlite3, tempfile, threading, time, zipfile
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from previews import PHOTO_PREVIEWS

from paths import RESOURCE_ROOT as ROOT, data_directory
DATA = data_directory()
DATA.mkdir(parents=True, exist_ok=True)
FILES = DATA / 'files'; FILES.mkdir(exist_ok=True)
DB = DATA / 'inventory.sqlite3'
LOCK = threading.RLock()
VERSION = '1.1.2'
IDLE = 1800; ABSOLUTE = 43200; MAX_FILE = 15 * 1024 * 1024
STATUSES = ['Available', 'Checked out', 'Leased', 'In repair', 'Broken', 'Lost / Missing', 'Sold', 'Donated', 'Disposed']
FIELDS = ['tag','description','purchase_date','cost','vendor','brand','model','serial','site','location','category','department','assigned_to','status','due_date','warranty_end','notes']
LISTS = ['site','location','category','department','person','vendor']

@contextmanager
def connection():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def fail(code, message): raise HTTPException(code, message)
def digest(token): return hashlib.sha256(token.encode()).hexdigest()
def password_hash(password):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
        fail(400, 'Use a password between 12 and 256 characters.')
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
def password_ok(password, encoded):
    try:
        salt, expected = encoded.split(':')
        return hmac.compare_digest(hashlib.scrypt(str(password).encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex(), expected)
    except (ValueError, TypeError): return False

def initialize():
    with connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT OR IGNORE INTO meta VALUES('schema','1');
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL COLLATE NOCASE UNIQUE,name TEXT NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','standard','readonly')),active INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,created REAL NOT NULL,last_seen REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(username TEXT PRIMARY KEY,count INTEGER NOT NULL,until REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY,tag TEXT NOT NULL COLLATE NOCASE UNIQUE,body TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL,updated TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,asset_id INTEGER REFERENCES assets(id),actor TEXT NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lists(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,value TEXT NOT NULL COLLATE NOCASE,UNIQUE(kind,value));
        CREATE TABLE IF NOT EXISTS attachments(id INTEGER PRIMARY KEY,asset_id INTEGER NOT NULL REFERENCES assets(id),filename TEXT NOT NULL,stored TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,size INTEGER NOT NULL,created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS history_asset ON history(asset_id,id);
        ''')
        for kind, value in [('site','Office'),('category','Computer equipment'),('category','Networking'),('category','Tools'),('category','Office equipment')]:
            c.execute('INSERT OR IGNORE INTO lists(kind,value) VALUES(?,?)', (kind,value))

def event(c, user, action, detail='', asset_id=None):
    c.execute('INSERT INTO history(asset_id,actor,event,detail,created) VALUES(?,?,?,?,?)', (asset_id,user['username'],action,detail,now()))

def public_user(u): return {k:u[k] for k in ['id','username','name','role','active']}
def authorized(request, write=False, admin=False):
    token = request.cookies.get('cmt_session_release','')
    with connection() as c:
        s=c.execute('SELECT s.*,u.username,u.name,u.role,u.active FROM sessions s JOIN users u ON u.id=s.user_id WHERE token=?',(digest(token),)).fetchone()
        if not s or not s['active'] or time.time()-s['last_seen']>IDLE or time.time()-s['created']>ABSOLUTE:
            if s: c.execute('DELETE FROM sessions WHERE token=?',(digest(token),))
            fail(401,'Please sign in again.')
        if request.method not in ['GET','HEAD'] and not hmac.compare_digest(request.headers.get('x-csrf-token',''),s['csrf']): fail(403,'Refresh the page and try again.')
        if admin and s['role']!='admin': fail(403,'Administrator access required.')
        if write and s['role']=='readonly': fail(403,'This account has read-only access.')
        c.execute('UPDATE sessions SET last_seen=? WHERE token=?',(time.time(),digest(token)))
        return dict(s)

def username(value):
    value=str(value).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,50}',value): fail(400,'Username: 3–50 letters, numbers, dots, hyphens or underscores.')
    return value

def clean_asset(b):
    if not isinstance(b,dict): fail(400,'Invalid asset record.')
    result={k:str(b.get(k,'') or '').strip() for k in FIELDS}
    if not result['tag'] or not result['description']: fail(400,'Asset tag and description are required.')
    for k,v in result.items():
        if len(v)>(10000 if k=='notes' else 500): fail(400,f'{k} is too long.')
    for k in ['purchase_date','due_date','warranty_end']:
        if result[k]:
            try: date.fromisoformat(result[k])
            except ValueError: fail(400,f'{k} must use YYYY-MM-DD.')
    if result['cost']:
        from decimal import Decimal, InvalidOperation
        try:
            d=Decimal(result['cost'])
            if not d.is_finite() or d<0 or d>Decimal('999999999999.99'): raise InvalidOperation()
            result['cost']=str(d.quantize(Decimal('.01')))
        except InvalidOperation: fail(400,'Cost must be a positive dollar amount or zero.')
    result['status']=result['status'] or 'Available'
    if result['status'] not in STATUSES: fail(400,'Invalid status.')
    if result['status'] in ['Checked out','Leased'] and not result['assigned_to']: fail(400,'Assign a person for checked out or leased equipment.')
    return result

def asset_row(r): return {**json.loads(r['body']),**{k:r[k] for k in ['id','version','created','updated']}}
def get_asset(c, asset_id):
    r=c.execute('SELECT * FROM assets WHERE id=? AND deleted=0',(asset_id,)).fetchone()
    if not r: fail(404,'Asset not found.')
    return asset_row(r)

def save_asset(c,b,u,asset_id=None,version=None):
    b=clean_asset(b)
    try:
        if asset_id is None:
            stamp=now(); r=c.execute('INSERT INTO assets(tag,body,created,updated) VALUES(?,?,?,?)',(b['tag'],json.dumps(b),stamp,stamp))
            asset_id=r.lastrowid; event(c,u,'Created',b['description'],asset_id)
        else:
            old=get_asset(c,asset_id)
            if old['version']!=version: fail(409,'This asset changed in another window. Reload it before saving.')
            c.execute('UPDATE assets SET tag=?,body=?,version=version+1,updated=? WHERE id=?',(b['tag'],json.dumps(b),now(),asset_id))
            changes={k:{'from':old.get(k,''),'to':b[k]} for k in FIELDS if old.get(k,'')!=b[k]}
            event(c,u,'Updated',json.dumps(changes,ensure_ascii=False),asset_id)
    except sqlite3.IntegrityError: fail(409,'That asset tag already exists, including archived assets. Choose a unique tag.')
    for k in ['site','location','category','department','vendor']:
        if b[k]: c.execute('INSERT OR IGNORE INTO lists(kind,value) VALUES(?,?)',(k,b[k]))
    if b['assigned_to']: c.execute('INSERT OR IGNORE INTO lists(kind,value) VALUES(?,?)',('person',b['assigned_to']))
    return get_asset(c,asset_id)

initialize()
app=FastAPI(title='CMT Asset Manager',docs_url=None,redoc_url=None,openapi_url=None)

@app.middleware('http')
async def local_only(request:Request,call_next):
    host=request.headers.get('host','')
    if not re.fullmatch(r'(127\.0\.0\.1|localhost)(:\d{1,5})?',host): return JSONResponse({'detail':'Local access only.'},400)
    if request.method not in ['GET','HEAD','OPTIONS']:
        origin=request.headers.get('origin')
        if origin and origin != 'http://'+host: return JSONResponse({'detail':'Cross-origin request blocked.'},403)
        if request.headers.get('sec-fetch-site')=='cross-site': return JSONResponse({'detail':'Cross-site request blocked.'},403)
        length=request.headers.get('content-length')
        try:
            if length and int(length)>220*1024*1024: return JSONResponse({'detail':'Upload too large.'},413)
        except ValueError: return JSONResponse({'detail':'Invalid request.'},400)
    response=await call_next(request)
    response.headers.update({'X-CMT-Application':'cmt-asset-manager','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
    return response

@app.get('/api/state')
def state():
    with connection() as c: return {'setup':c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0,'version':VERSION}

@app.post('/api/setup')
def setup(b:dict):
    with LOCK,connection() as c:
        if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]: fail(409,'Administrator account already exists.')
        name=str(b.get('name','')).strip()[:100]
        if not name: fail(400,'Your name is required.')
        c.execute('INSERT INTO users(username,name,password,role,created) VALUES(?,?,?,?,?)',(username(b.get('username','')),name,password_hash(b.get('password','')),'admin',now()))
    return {'ok':True}

@app.post('/api/login')
def login(b:dict):
    name=str(b.get('username','')).strip()[:100].lower(); pw=str(b.get('password',''))
    if len(pw)>256: fail(400,'Invalid credentials.')
    with LOCK,connection() as c:
        attempt=c.execute('SELECT * FROM attempts WHERE username=?',(name,)).fetchone()
        if attempt and attempt['count']>=5 and attempt['until']>time.time(): fail(429,'Too many attempts. Wait 5 minutes before trying again.')
        u=c.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
        # Fixed work on unknown accounts too.
        encoded=u['password'] if u else '00'*16+':'+'00'*64
        valid=password_ok(pw,encoded)
        if not u or not u['active'] or not valid:
            count=(attempt['count'] if attempt and attempt['until']>time.time() else 0)+1
            c.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(name,count,time.time()+300))
            c.commit(); fail(401,'Incorrect username or password.')
        c.execute('DELETE FROM attempts WHERE username=?',(name,))
        token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32); t=time.time()
        c.execute('DELETE FROM sessions WHERE last_seen<? OR created<?',(t-IDLE,t-ABSOLUTE))
        c.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(digest(token),u['id'],csrf,t,t))
        event(c,u,'Signed in')
        response=JSONResponse({'user':public_user(u),'csrf':csrf})
        response.set_cookie('cmt_session_release',token,httponly=True,samesite='strict',path='/')
        return response

@app.get('/api/me')
def me(request:Request):
    u=authorized(request)
    return {'user':{'id':u['user_id'],**{k:u[k] for k in ['username','name','role','active']}},'csrf':u['csrf']}

@app.post('/api/logout')
def logout(request:Request):
    u=authorized(request)
    with connection() as c:
        c.execute('DELETE FROM sessions WHERE token=?',(u['token'],)); event(c,u,'Signed out')
    r=JSONResponse({'ok':True}); r.delete_cookie('cmt_session_release'); return r

@app.post('/api/password')
def change_password(request:Request,b:dict):
    u=authorized(request)
    with LOCK,connection() as c:
        row=c.execute('SELECT * FROM users WHERE id=?',(u['user_id'],)).fetchone()
        if not password_ok(b.get('current',''),row['password']): fail(400,'Current password is incorrect.')
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(b.get('password','')),u['user_id']))
        c.execute('DELETE FROM sessions WHERE user_id=?',(u['user_id'],)); event(c,u,'Changed password')
    return {'ok':True}

@app.get('/api/users')
def users(request:Request):
    authorized(request,admin=True)
    with connection() as c: return [public_user(u) for u in c.execute('SELECT * FROM users ORDER BY username')]

@app.post('/api/users')
def add_user(request:Request,b:dict):
    u=authorized(request,admin=True); role=b.get('role'); name=str(b.get('name','')).strip()[:100]
    if role not in ['admin','standard','readonly'] or not name: fail(400,'Name and valid role are required.')
    with LOCK,connection() as c:
        try: c.execute('INSERT INTO users(username,name,password,role,created) VALUES(?,?,?,?,?)',(username(b.get('username','')),name,password_hash(b.get('password','')),role,now()))
        except sqlite3.IntegrityError: fail(409,'Username already exists.')
        event(c,u,'Added user',str(b.get('username')))
    return {'ok':True}

@app.put('/api/users/{user_id}')
def update_user(user_id:int,request:Request,b:dict):
    u=authorized(request,admin=True)
    with LOCK,connection() as c:
        old=c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not old: fail(404,'User not found.')
        role=b.get('role',old['role']); active=b.get('active',bool(old['active'])); name=str(b.get('name',old['name'])).strip()[:100]
        if role not in ['admin','standard','readonly'] or not isinstance(active,bool) or not name: fail(400,'Invalid account details.')
        if old['role']=='admin' and old['active'] and (role!='admin' or not active):
            if c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]<=1: fail(400,'Keep at least one active administrator.')
        if user_id==u['user_id'] and (not active or role!='admin'): fail(400,'Use another administrator to change your own access.')
        pw=password_hash(b['password']) if b.get('password') else old['password']
        c.execute('UPDATE users SET name=?,role=?,active=?,password=? WHERE id=?',(name,role,int(active),pw,user_id))
        c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,)); event(c,u,'Updated user',old['username'])
    return {'ok':True}

@app.delete('/api/users/{user_id}')
def delete_user(user_id:int,request:Request,b:dict):
    u=authorized(request,admin=True)
    with LOCK,connection() as c:
        target=c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not target: fail(404,'User not found.')
        if target['role']=='admin' and target['active'] and c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]<=1:
            fail(400,'The last active administrator cannot be deleted.')
        if user_id==u['user_id']: fail(400,'You cannot delete the account you are signed in with.')
        if b.get('username')!=target['username']: fail(400,'Type the exact username to confirm deletion.')
        c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
        c.execute('DELETE FROM attempts WHERE username=?',(target['username'].lower(),))
        c.execute('DELETE FROM meta WHERE key=?',('appearance:'+str(user_id),))
        c.execute('DELETE FROM users WHERE id=?',(user_id,))
        event(c,u,'Deleted user',f"{target['username']} ({target['name']}); role: {target['role']}")
    return {'ok':True}

@app.get('/api/assets')
def assets(request:Request):
    authorized(request)
    with connection() as c: return [asset_row(r) for r in c.execute('SELECT * FROM assets WHERE deleted=0 ORDER BY id DESC')]

@app.post('/api/assets')
def add_asset(request:Request,b:dict):
    u=authorized(request,write=True)
    with LOCK,connection() as c: return save_asset(c,b,u)

@app.get('/api/assets/{asset_id}')
def detail(asset_id:int,request:Request):
    authorized(request)
    with connection() as c:
        a=get_asset(c,asset_id)
        a['history']=[dict(r) for r in c.execute('SELECT * FROM history WHERE asset_id=? ORDER BY id DESC',(asset_id,))]
        a['attachments']=[dict(r) for r in c.execute('SELECT id,filename,kind,size,created FROM attachments WHERE asset_id=? ORDER BY id DESC',(asset_id,))]
        return a

@app.put('/api/assets/{asset_id}')
def edit_asset(asset_id:int,request:Request,b:dict):
    u=authorized(request,write=True)
    with LOCK,connection() as c: return save_asset(c,b,u,asset_id,b.get('version'))

@app.delete('/api/assets/{asset_id}')
def archive_asset(asset_id:int,request:Request,b:dict):
    u=authorized(request,admin=True)
    with LOCK,connection() as c:
        a=get_asset(c,asset_id)
        if a['version']!=b.get('version'): fail(409,'Asset changed. Reload and try again.')
        c.execute('UPDATE assets SET deleted=1,version=version+1,updated=? WHERE id=?',(now(),asset_id)); event(c,u,'Archived',a['tag'],asset_id)
    return {'ok':True}

@app.get('/api/archived')
def archived(request:Request):
    authorized(request,admin=True)
    with connection() as c: return [asset_row(r) for r in c.execute('SELECT * FROM assets WHERE deleted=1 ORDER BY id DESC')]

@app.post('/api/assets/{asset_id}/restore')
def unarchive(asset_id:int,request:Request):
    u=authorized(request,admin=True)
    with LOCK,connection() as c:
        if not c.execute('SELECT id FROM assets WHERE id=? AND deleted=1',(asset_id,)).fetchone(): fail(404,'Archived asset not found.')
        c.execute('UPDATE assets SET deleted=0,version=version+1,updated=? WHERE id=?',(now(),asset_id)); event(c,u,'Restored from archive','',asset_id)
    return {'ok':True}

@app.get('/api/lists')
def lists(request:Request):
    authorized(request)
    with connection() as c: return {k:[dict(r) for r in c.execute('SELECT id,value FROM lists WHERE kind=? ORDER BY value',(k,))] for k in LISTS}

@app.post('/api/lists')
def add_list(request:Request,b:dict):
    u=authorized(request,write=True); kind=b.get('kind'); value=str(b.get('value','')).strip()
    if kind not in LISTS or not value or len(value)>500: fail(400,'Choose a list and enter a value up to 500 characters.')
    with LOCK,connection() as c:
        c.execute('INSERT OR IGNORE INTO lists(kind,value) VALUES(?,?)',(kind,value)); event(c,u,'Added list value',f'{kind}: {value}')
    return {'ok':True}

@app.delete('/api/lists/{list_id}')
def delete_list(list_id:int,request:Request):
    u=authorized(request,admin=True)
    with LOCK,connection() as c:
        r=c.execute('SELECT * FROM lists WHERE id=?',(list_id,)).fetchone()
        if r:
            c.execute('DELETE FROM lists WHERE id=?',(list_id,)); event(c,u,'Removed list suggestion',r['value'])
    return {'ok':True}

@app.post('/api/assets/{asset_id}/attachments')
def upload(asset_id:int,request:Request,file:UploadFile=File(...),kind:str=Form('document')):
    u=authorized(request,write=True)
    filename=Path((file.filename or 'attachment').replace('\\','/')).name[:150]
    ext=Path(filename).suffix.lower()
    allowed={'.png','.jpg','.jpeg','.gif','.webp','.pdf','.txt','.csv','.docx','.xlsx'}
    if ext not in allowed or kind not in ['photo','document']: fail(400,'Supported: PNG, JPG, GIF, WebP, PDF, TXT, CSV, DOCX and XLSX.')
    if kind=='photo' and ext not in {'.png','.jpg','.jpeg','.gif','.webp'}: fail(400,'Choose an image for an asset photo.')
    content=file.file.read(MAX_FILE+1)
    if len(content)>MAX_FILE: fail(413,'Each attachment must be 15 MB or smaller.')
    if not content: fail(400,'Empty file.')
    if kind=='photo':
        valid=(ext=='.png' and content.startswith(b'\x89PNG\r\n\x1a\n')) or (ext in ['.jpg','.jpeg'] and content.startswith(b'\xff\xd8\xff')) or (ext=='.gif' and content[:6] in [b'GIF87a',b'GIF89a']) or (ext=='.webp' and content[:4]==b'RIFF' and content[8:12]==b'WEBP')
        if not valid: fail(400,'Image content does not match its extension.')
    stored=secrets.token_hex(24)+ext
    with LOCK,connection() as c:
        get_asset(c,asset_id); path=FILES/stored
        try:
            path.write_bytes(content)
            c.execute('INSERT INTO attachments(asset_id,filename,stored,kind,size,created) VALUES(?,?,?,?,?,?)',(asset_id,filename,stored,kind,len(content),now()))
            event(c,u,'Added attachment',filename,asset_id)
        except Exception: path.unlink(missing_ok=True); raise
    return {'ok':True}

@app.get('/api/attachments/{attachment_id}')
def download(attachment_id:int,request:Request):
    authorized(request)
    with connection() as c: r=c.execute('SELECT * FROM attachments WHERE id=?',(attachment_id,)).fetchone()
    if not r or not (FILES/r['stored']).is_file(): fail(404,'Attachment not found.')
    images={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.webp':'image/webp'}
    if r['kind']=='photo': return FileResponse(FILES/r['stored'],media_type=images.get(Path(r['stored']).suffix,'application/octet-stream'))
    if Path(r['stored']).suffix.lower()=='.pdf':
        return FileResponse(FILES/r['stored'],filename=r['filename'],media_type='application/pdf',content_disposition_type='inline')
    return FileResponse(FILES/r['stored'],filename=r['filename'],media_type='application/octet-stream')

@app.get('/api/attachments/{attachment_id}/preview')
def photo_preview(attachment_id:int,request:Request):
    authorized(request)
    with connection() as c:
        row=c.execute('SELECT * FROM attachments WHERE id=?',(attachment_id,)).fetchone()
    if not row or row['kind']!='photo': fail(404,'Photo not found.')
    path=FILES/row['stored']
    if not path.is_file(): fail(404,'Photo not found.')
    result=PHOTO_PREVIEWS.get(path)
    if result:
        content,media_type=result
        return Response(content,media_type=media_type)
    # A photo accepted by an earlier version may not decode with Pillow.
    # Preserve access to that file rather than breaking the equipment view.
    return download(attachment_id,request)

@app.delete('/api/attachments/{attachment_id}')
def delete_attachment(attachment_id:int,request:Request):
    u=authorized(request,write=True)
    with LOCK,connection() as c:
        r=c.execute('SELECT * FROM attachments WHERE id=?',(attachment_id,)).fetchone()
        if r:
            c.execute('DELETE FROM attachments WHERE id=?',(attachment_id,)); event(c,u,'Removed attachment',r['filename'],r['asset_id'])
            # Preserve unreferenced bytes until backup/maintenance; avoids half-applied deletion.
    return {'ok':True}

@app.get('/api/history')
def history(request:Request):
    authorized(request,admin=True)
    with connection() as c: return [dict(r) for r in c.execute('SELECT * FROM history ORDER BY id DESC LIMIT 1000')]

@app.get('/api/export.csv')
def export_csv(request:Request):
    authorized(request); s=io.StringIO(newline=''); w=csv.writer(s); w.writerow(FIELDS)
    with connection() as c:
        for r in c.execute('SELECT * FROM assets WHERE deleted=0 ORDER BY id'):
            a=asset_row(r); w.writerow([safe_csv(a.get(k,'')) for k in FIELDS])
    return Response('\ufeff'+s.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="CMT_Inventory.csv"'})

def safe_csv(v):
    v=str(v)
    return "'"+v if v.lstrip().startswith(('=','+','-','@','\t','\r')) else v

@app.get('/api/export.xlsx')
def export_xlsx(request:Request):
    authorized(request)
    with connection() as c: rows=[FIELDS]+[[str(asset_row(r).get(k,'')) for k in FIELDS] for r in c.execute('SELECT * FROM assets WHERE deleted=0 ORDER BY id')]
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Inventory" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        def cell(value, numeric=False):
            if numeric and value: return '<c t="n"><v>'+escape(value)+'</v></c>'
            return '<c t="inlineStr"><is><t xml:space="preserve">'+escape(''.join(ch for ch in value if ord(ch)>=32 or ch in '\t\n\r'))+'</t></is></c>'
        content=''.join('<row>'+''.join(cell(v, ri>0 and ci==FIELDS.index('cost')) for ci,v in enumerate(row))+'</row>' for ri,row in enumerate(rows))
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+content+'</sheetData></worksheet>')
    return Response(out.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="CMT_Inventory.xlsx"'})

@app.post('/api/import')
def import_csv(request:Request,file:UploadFile=File(...)):
    u=authorized(request,write=True); content=file.file.read(5*1024*1024+1)
    if len(content)>5*1024*1024: fail(413,'CSV must be under 5 MB.')
    try:
        reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        if not reader.fieldnames or not {'tag','description'}.issubset(reader.fieldnames): fail(400,'CSV headers must include tag and description. Download the template first.')
        records=list(reader)
    except (UnicodeError,csv.Error): fail(400,'Use a UTF-8 CSV file.')
    if not records or len(records)>10000: fail(400,'Import between 1 and 10,000 assets.')
    with LOCK,connection() as c:
        for line,b in enumerate(records,2):
            try: save_asset(c,b,u)
            except HTTPException as e: fail(e.status_code,f'Row {line}: {e.detail} No records were imported.')
        event(c,u,'Imported CSV',f'{len(records)} assets')
    return {'count':len(records)}

@app.get('/api/import-template.csv')
def import_template(request:Request):
    authorized(request); s=io.StringIO(); csv.writer(s).writerow(FIELDS)
    return Response(s.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="CMT_Import_Template.csv"'})

@app.get('/api/backup')
def backup(request:Request):
    u=authorized(request,admin=True)
    with LOCK, tempfile.TemporaryDirectory() as tmp:
        target=Path(tmp)/'inventory.sqlite3'
        with connection() as c:
            event(c,u,'Downloaded backup'); c.commit()
            dest=sqlite3.connect(target)
            try: c.backup(dest)
            finally: dest.close()
        # Sessions are intentionally excluded from portable backups.
        # sqlite3's transaction context commits/rolls back but does not close.
        # Close explicitly before ZIP creation and Windows temp-file cleanup.
        with closing(sqlite3.connect(target)) as c, c:
            c.execute('DELETE FROM sessions')
            c.execute('DELETE FROM attempts')
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(target,'inventory.sqlite3')
            with connection() as c: filenames=[r[0] for r in c.execute('SELECT stored FROM attachments')]
            for name in filenames:
                p=FILES/name
                if not p.is_file(): fail(409,'An attachment is missing. Resolve it before backing up.')
                z.write(p,'files/'+name)
            z.writestr('manifest.json',json.dumps({'application':'CMT Asset Manager','schema':1,'version':VERSION,'created':now()}))
    return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="CMT_Backup_'+date.today().isoformat()+'.zip"'})

@app.post('/api/restore')
def stage_restore(request:Request,password:str=Form(...),file:UploadFile=File(...)):
    u=authorized(request,admin=True)
    with connection() as c: row=c.execute('SELECT password FROM users WHERE id=?',(u['user_id'],)).fetchone()
    if not password_ok(password,row['password']): fail(400,'Administrator password is incorrect.')
    from recovery import validate_backup
    with LOCK:
        p=DATA/'restore-upload.tmp'
        try:
            with p.open('wb') as f:
                total=0
                while chunk:=file.file.read(1024*1024):
                    total+=len(chunk)
                    if total>200*1024*1024: fail(413,'Restore file must be 200 MB or smaller. See the user guide for larger backups.')
                    f.write(chunk)
            validate_backup(p)
            os.replace(p,DATA/'pending-restore.zip')
            with connection() as c: event(c,u,'Staged restore','Applies on next launch')
        except (ValueError,zipfile.BadZipFile,sqlite3.DatabaseError) as e: fail(400,'Invalid CMT backup: '+str(e))
        finally: p.unlink(missing_ok=True)
    return {'ok':True,'message':'Backup staged. Stop the application window, then start CMT Asset Manager again. Use the accounts and passwords from the backup.'}

@app.delete('/api/restore')
def cancel_restore(request:Request):
    u=authorized(request,admin=True)
    with LOCK,connection() as c:
        (DATA/'pending-restore.zip').unlink(missing_ok=True); event(c,u,'Cancelled staged restore')
    return {'ok':True}

@app.get('/api/settings')
def settings(request:Request):
    authorized(request,admin=True)
    return {'version':VERSION,'data_directory':str(DATA),'pending_restore':(DATA/'pending-restore.zip').exists(),'idle_minutes':IDLE//60}

@app.get('/api/preferences')
def preferences(request:Request):
    u=authorized(request)
    with connection() as c:
        row=c.execute('SELECT value FROM meta WHERE key=?',('appearance:'+str(u['user_id']),)).fetchone()
    return json.loads(row['value']) if row else {'mode':'system','accent':'#007f78'}

@app.put('/api/preferences')
def save_preferences(request:Request,b:dict):
    # Appearance is a personal preference, available to read-only accounts too.
    u=authorized(request)
    mode=b.get('mode'); accent=b.get('accent')
    if mode not in ['light','dark','system'] or not isinstance(accent,str) or not re.fullmatch(r'#[a-fA-F0-9]{6}',accent):
        fail(400,'Choose a valid appearance mode and six-digit color.')
    value={'mode':mode,'accent':accent.lower()}
    with LOCK,connection() as c:
        c.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',('appearance:'+str(u['user_id']),json.dumps(value)))
    return value

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
