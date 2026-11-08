"""Integration checks: use an isolated temp data directory, never real inventory."""
import base64, io, json, os, sqlite3, sys, tempfile, time, unittest, zipfile
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
TEST_DATA=tempfile.TemporaryDirectory()
os.environ['CMT_DATA_DIR']=TEST_DATA.name
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import app
from recovery import validate_backup, apply_pending

@contextmanager
def strict_windows_sqlite_handles():
    """Detect live database handles at temp cleanup, even on Linux."""
    real_connect=sqlite3.connect
    real_temp=tempfile.TemporaryDirectory
    opened={}
    class TrackedConnection(sqlite3.Connection):
        def close(self):
            try: super().close()
            finally: opened.pop(id(self),None)
    def connect(path,*args,**kwargs):
        kwargs['factory']=TrackedConnection
        kwargs['check_same_thread']=False
        conn=real_connect(path,*args,**kwargs)
        opened[id(conn)]=(conn,Path(path).resolve())
        return conn
    class StrictTempDirectory(real_temp):
        def cleanup(self):
            for conn,path in opened.values():
                if path.is_relative_to(Path(self.name).resolve()):
                    raise AssertionError('SQLite handle still open during temporary-directory cleanup: '+str(path))
            return super().cleanup()
    try:
        with patch.object(sqlite3,'connect',connect),patch.object(tempfile,'TemporaryDirectory',StrictTempDirectory):
            yield opened
            assert not opened, 'Database handles leaked after operation'
    finally:
        for conn,path in list(opened.values()): conn.close()

class InventoryTests(unittest.TestCase):
    def setUp(self):
        with app.connection() as c:
            for table in ['sessions','attempts','attachments','history','assets','users','lists']:
                c.execute('DELETE FROM '+table)
            c.execute("DELETE FROM meta WHERE key LIKE 'appearance:%'")
        for p in app.FILES.iterdir(): p.unlink()
        (app.DATA/'pending-restore.zip').unlink(missing_ok=True)
        self.client=TestClient(app.app,base_url='http://127.0.0.1:8765')
        self.assertEqual(self.client.post('/api/setup',json={'username':'matt','name':'Matthew Miles','password':'A secure password 123'}).status_code,200)
        self.login()
    def login(self,client=None,name='matt',password='A secure password 123'):
        client=client or self.client
        r=client.post('/api/login',json={'username':name,'password':password})
        self.assertEqual(r.status_code,200,r.text);client.headers['X-CSRF-Token']=r.json()['csrf'];return client
    def create(self,**kw):
        r=self.client.post('/api/assets',json={'tag':'CMT-001','description':'Office PC','cost':'278.99',**kw})
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def add_user(self,role):
        r=self.client.post('/api/users',json={'username':role,'name':role.title(),'role':role,'password':'A secure password 123'})
        self.assertEqual(r.status_code,200,r.text)
        return self.login(TestClient(app.app,base_url='http://127.0.0.1:8765'),role)
    def test_setup_and_host_origin_guards(self):
        self.assertEqual(self.client.get('/api/state').json()['setup'],False)
        self.assertEqual(self.client.post('/api/setup',json={}).status_code,409)
        self.assertEqual(self.client.get('/api/assets',headers={'host':'evil.example'}).status_code,400)
        self.assertEqual(self.client.post('/api/assets',json={},headers={'origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/assets',json={},headers={'X-CSRF-Token':'bad'}).status_code,403)
        guest=TestClient(app.app,base_url='http://localhost:8765')
        for path in ['/api/assets','/api/users','/api/backup','/api/export.xlsx','/api/attachments/1']:
            self.assertEqual(guest.get(path).status_code,401,path)
    def test_password_storage_and_session(self):
        with app.connection() as c:
            row=c.execute('SELECT password FROM users').fetchone()
            self.assertNotIn('A secure',row[0]);self.assertTrue(app.password_ok('A secure password 123',row[0]))
            token=self.client.cookies.get('cmt_session_release')
            self.assertNotEqual(c.execute('SELECT token FROM sessions').fetchone()[0],token)
            c.execute('UPDATE sessions SET last_seen=?',(time.time()-1900,))
        self.assertEqual(self.client.get('/api/assets').status_code,401)
    def test_login_rate_limit(self):
        for _ in range(5):self.assertEqual(self.client.post('/api/login',json={'username':'matt','password':'incorrect'}).status_code,401)
        self.assertEqual(self.client.post('/api/login',json={'username':'matt','password':'correct?'}).status_code,429)
    def test_roles_and_account_deactivation(self):
        a=self.create();ro=self.add_user('readonly');standard=self.add_user('standard')
        self.assertEqual(ro.get('/api/assets').status_code,200)
        self.assertEqual(ro.put('/api/assets/'+str(a['id']),json=a).status_code,403)
        self.assertEqual(ro.post('/api/lists',json={'kind':'site','value':'x'}).status_code,403)
        self.assertEqual(standard.get('/api/backup').status_code,403)
        self.assertEqual(standard.post('/api/users',json={}).status_code,403)
        self.assertEqual(standard.request('DELETE','/api/assets/'+str(a['id']),json={}).status_code,403)
        self.assertEqual(standard.put('/api/assets/'+str(a['id']),json={**a,'location':'Desk'}).status_code,200)
        users=self.client.get('/api/users').json();uid=next(u['id'] for u in users if u['username']=='standard')
        self.assertEqual(self.client.put('/api/users/'+str(uid),json={'active':False}).status_code,200)
        self.assertEqual(standard.get('/api/assets').status_code,401)
        adminid=next(u['id'] for u in users if u['username']=='matt')
        self.assertEqual(self.client.put('/api/users/'+str(adminid),json={'role':'readonly'}).status_code,400)
    def test_asset_lifecycle_concurrency_and_archive(self):
        a=self.create();id=a['id'];self.assertEqual(self.client.post('/api/assets',json=a).status_code,409)
        b=self.client.put(f'/api/assets/{id}',json={**a,'status':'Checked out','assigned_to':'Matthew','due_date':'2026-11-01'}).json()
        self.assertEqual(b['version'],2)
        self.assertEqual(self.client.put(f'/api/assets/{id}',json=a).status_code,409)
        self.assertEqual(self.client.request('DELETE',f'/api/assets/{id}',json={'version':b['version']}).status_code,200)
        self.assertEqual(self.client.get('/api/assets').json(),[])
        self.assertEqual(len(self.client.get('/api/archived').json()),1)
        self.assertEqual(self.client.post(f'/api/assets/{id}/restore').status_code,200)
        d=self.client.get(f'/api/assets/{id}').json();self.assertEqual(len(d['history']),4)
    def test_invalid_data(self):
        for values in [{'cost':'NaN'},{'cost':'-1'},{'purchase_date':'10/29/2026'},{'status':'Other'},{'status':'Checked out'},{'tag':''}]:
            r=self.client.post('/api/assets',json={'tag':'X','description':'test',**values});self.assertEqual(r.status_code,400,r.text)
    def test_photo_preview_is_small_cached_and_authorized(self):
        from PIL import Image
        original=io.BytesIO()
        image=Image.new('RGB',(2400,1200),'#245eea')
        exif=Image.Exif();exif[274]=6
        image.save(original,format='JPEG',exif=exif);image.close()
        content=original.getvalue();a=self.create()
        self.assertEqual(self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'photo'},files={'file':('camera.jpg',content)}).status_code,200)
        fid=self.client.get('/api/assets/'+str(a['id'])).json()['attachments'][0]['id']
        url='/api/attachments/'+str(fid)
        preview=self.client.get(url+'/preview')
        self.assertEqual(preview.status_code,200,preview.text[:100])
        self.assertEqual(preview.headers['content-type'],'image/jpeg')
        self.assertEqual(preview.headers['cache-control'],'no-store')
        self.assertLess(len(preview.content),len(content))
        with Image.open(io.BytesIO(preview.content)) as thumb:
            self.assertEqual(thumb.size,(256,512))
        with patch.object(app.PHOTO_PREVIEWS,'render',side_effect=AssertionError('Original photo decoded again')):
            self.assertEqual(self.client.get(url+'/preview').content,preview.content)
        self.assertEqual(self.client.get(url).content,content)
        guest=TestClient(app.app,base_url='http://127.0.0.1:8765')
        self.assertEqual(guest.get(url+'/preview').status_code,401)
        self.assertEqual(self.add_user('readonly').get(url+'/preview').content,preview.content)
        self.assertEqual(self.client.delete(url).status_code,200)
        self.assertEqual(self.client.get(url+'/preview').status_code,404)

    def test_transparent_preview_preserves_alpha_and_original(self):
        from PIL import Image,ImageDraw
        source=Image.new('RGBA',(1600,1200),(20,80,120,0))
        ImageDraw.Draw(source).rectangle((300,300,1000,900),fill=(20,80,120,255))
        out=io.BytesIO();source.save(out,format='PNG');source.close()
        a=self.create();content=out.getvalue()
        self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'photo'},files={'file':('transparent.png',content)})
        fid=self.client.get('/api/assets/'+str(a['id'])).json()['attachments'][0]['id']
        url='/api/attachments/'+str(fid)
        r=self.client.get(url+'/preview')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['content-type'],'image/png')
        with Image.open(io.BytesIO(r.content)) as image:
            self.assertEqual(image.size,(512,384))
            self.assertEqual(image.getchannel('A').getextrema(),(0,255))
        self.assertEqual(self.client.get(url).content,content)

    def test_preview_fallback_and_nonphoto_rejection(self):
        a=self.create();content=b'\x89PNG\r\n\x1a\nlegacy invalid image'
        self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'photo'},files={'file':('legacy.png',content)})
        fid=self.client.get('/api/assets/'+str(a['id'])).json()['attachments'][0]['id']
        self.assertEqual(self.client.get('/api/attachments/'+str(fid)+'/preview').content,content)
        self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'document'},files={'file':('note.txt',b'note')})
        fid=self.client.get('/api/assets/'+str(a['id'])).json()['attachments'][0]['id']
        self.assertEqual(self.client.get('/api/attachments/'+str(fid)+'/preview').status_code,404)

    def test_pdf_opens_inline_and_other_documents_download(self):
        a=self.create()
        for filename,content,media,disposition in [('receipt.PDF',b'%PDF-1.4\n%%EOF','application/pdf','inline'),('receipt.txt',b'receipt','application/octet-stream','attachment')]:
            r=self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'document'},files={'file':(filename,content)})
            self.assertEqual(r.status_code,200,r.text)
            fid=self.client.get('/api/assets/'+str(a['id'])).json()['attachments'][0]['id']
            url='/api/attachments/'+str(fid)
            r=self.client.get(url)
            self.assertEqual(r.content,content)
            self.assertEqual(r.headers['content-type'],media)
            self.assertTrue(r.headers['content-disposition'].startswith(disposition+';'))
            self.assertEqual(TestClient(app.app,base_url='http://127.0.0.1:8765').get(url).status_code,401)

    def test_attachment_upload_access_and_remove(self):
        a=self.create();png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1kAAAAASUVORK5CYII=')
        r=self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'photo'},files={'file':('pc.png',png,'image/png')});self.assertEqual(r.status_code,200,r.text)
        d=self.client.get('/api/assets/'+str(a['id'])).json();fid=d['attachments'][0]['id']
        self.assertEqual(self.client.get('/api/attachments/'+str(fid)).content,png)
        self.assertEqual(self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'photo'},files={'file':('bad.png',b'not image')}).status_code,400)
        self.assertEqual(self.client.delete('/api/attachments/'+str(fid)).status_code,200)
        self.assertEqual(self.client.get('/api/attachments/'+str(fid)).status_code,404)
    def test_csv_atomicity_and_exports(self):
        self.create(description='=HYPERLINK("x")')
        csv=self.client.get('/api/export.csv');self.assertIn("'=HYPERLINK",csv.text)
        xlsx=self.client.get('/api/export.xlsx')
        with zipfile.ZipFile(io.BytesIO(xlsx.content)) as z:
            xml=z.read('xl/worksheets/sheet1.xml');self.assertIn(b'inlineStr',xml);self.assertNotIn(b'<f>',xml)
        r=self.client.post('/api/import',files={'file':('data.csv',b'tag,description,cost\nNEW,Good,20\nBAD,Bad,-1\n','text/csv')})
        self.assertEqual(r.status_code,400,r.text);self.assertEqual(len(self.client.get('/api/assets').json()),1)
        r=self.client.post('/api/import',files={'file':('data.csv',b'tag,description,cost\nNEW,Good,20\n','text/csv')})
        self.assertEqual(r.json()['count'],1)
    def test_backup_restore_and_safety_snapshot(self):
        a=self.create();self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'document'},files={'file':('receipt.txt',b'receipt')})
        backup=self.client.get('/api/backup');self.assertEqual(backup.status_code,200)
        p=app.DATA/'test-backup.zip';p.write_bytes(backup.content);validate_backup(p)
        self.create(tag='SECOND')
        r=self.client.post('/api/restore',data={'password':'wrong'},files={'file':('backup.zip',backup.content)});self.assertEqual(r.status_code,400)
        r=self.client.post('/api/restore',data={'password':'A secure password 123'},files={'file':('backup.zip',backup.content)});self.assertEqual(r.status_code,200,r.text)
        apply_pending(app.DATA)
        self.assertEqual(self.client.get('/api/assets').status_code,401)
        self.login();self.assertEqual(len(self.client.get('/api/assets').json()),1)
        self.assertTrue(list((app.DATA/'safety').glob('*/inventory.sqlite3')))
        self.assertEqual(len(self.client.get('/api/assets/'+str(a['id'])).json()['attachments']),1)
    def test_malicious_archive_rejected(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('../escape.txt','bad');z.writestr('manifest.json','{}');z.writestr('inventory.sqlite3','bad')
        p=app.DATA/'bad.zip';p.write_bytes(b.getvalue())
        with self.assertRaises(ValueError):validate_backup(p)
    def test_interrupted_restore_rolls_back(self):
        import shutil
        self.create()
        safety=app.DATA/'safety'/'interrupted-test';safety.mkdir(parents=True,exist_ok=True)
        shutil.copy2(app.DB,safety/'inventory.sqlite3')
        shutil.copytree(app.FILES,safety/'files',dirs_exist_ok=True)
        (app.DATA/'restore-journal.json').write_text(json.dumps({'snapshot':'interrupted-test'}))
        with app.connection() as c:c.execute('DELETE FROM history');c.execute('DELETE FROM assets')
        apply_pending(app.DATA)
        self.assertEqual(len(self.client.get('/api/assets').json()),1)
        self.assertFalse((app.DATA/'restore-journal.json').exists())
    def test_backup_missing_attachment_rejected(self):
        a=self.create()
        self.client.post(f"/api/assets/{a['id']}/attachments",data={'kind':'document'},files={'file':('receipt.txt',b'receipt')})
        backup=self.client.get('/api/backup')
        p=app.DATA/'incomplete.zip'
        with zipfile.ZipFile(io.BytesIO(backup.content)) as source,zipfile.ZipFile(p,'w') as dest:
            for name in source.namelist():
                if not name.startswith('files/'):dest.writestr(name,source.read(name))
        with self.assertRaises(ValueError):validate_backup(p)
    def test_backup_closes_handles_before_cleanup(self):
        self.create()
        with strict_windows_sqlite_handles():
            r=self.client.get('/api/backup')
            self.assertEqual(r.status_code,200)
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                self.assertIsNone(z.testzip())
    def test_restore_validation_closes_handles_before_cleanup(self):
        self.create()
        backup=self.client.get('/api/backup')
        p=app.DATA/'strict-backup.zip';p.write_bytes(backup.content)
        with strict_windows_sqlite_handles():
            validate_backup(p,app.DATA/'validated-copy')
    def test_failed_validation_closes_handles(self):
        self.create()
        backup=self.client.get('/api/backup')
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'inventory.sqlite3'
            with zipfile.ZipFile(io.BytesIO(backup.content)) as z:db.write_bytes(z.read('inventory.sqlite3'))
            c=sqlite3.connect(db)
            try:
                c.execute("UPDATE meta SET value='999' WHERE key='schema'");c.commit()
            finally:c.close()
            p=app.DATA/'invalid-schema.zip'
            with zipfile.ZipFile(p,'w') as z:
                z.write(db,'inventory.sqlite3')
                z.writestr('manifest.json',json.dumps({'application':'CMT Asset Manager','schema':1}))
        with strict_windows_sqlite_handles():
            with self.assertRaisesRegex(ValueError,'Unsupported database schema'):
                validate_backup(p)
    def test_personal_appearance_permissions_and_isolation(self):
        readonly=self.add_user('readonly')
        self.assertEqual(self.client.get('/api/preferences').json(),{'mode':'system','accent':'#007f78'})
        r=readonly.put('/api/preferences',json={'mode':'dark','accent':'#AABBCC'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(readonly.get('/api/preferences').json(),{'mode':'dark','accent':'#aabbcc'})
        self.assertEqual(self.client.get('/api/preferences').json()['mode'],'system')
        self.assertEqual(readonly.put('/api/preferences',json={'mode':'dark','accent':'red;url(x)'}).status_code,400)
        self.assertEqual(readonly.put('/api/preferences',json={'mode':'other','accent':'#123456'}).status_code,400)
        self.assertEqual(readonly.put('/api/preferences',json={'mode':'light','accent':'#123456'},headers={'X-CSRF-Token':'bad'}).status_code,403)
        guest=TestClient(app.app,base_url='http://127.0.0.1:8766')
        self.assertEqual(guest.get('/api/preferences').status_code,401)
    def test_appearance_included_in_backup(self):
        self.client.put('/api/preferences',json={'mode':'light','accent':'#123456'})
        backup=self.client.get('/api/backup');p=app.DATA/'appearance-backup.zip';p.write_bytes(backup.content)
        destination=app.DATA/'appearance-restore';validate_backup(p,destination)
        c=sqlite3.connect(destination/'inventory.sqlite3')
        try:
            value=json.loads(c.execute("SELECT value FROM meta WHERE key LIKE 'appearance:%'").fetchone()[0])
            self.assertEqual(value,{'mode':'light','accent':'#123456'})
        finally:c.close()
    def test_user_deletion_preserves_inventory_and_history(self):
        standard=self.add_user('standard')
        r=standard.post('/api/assets',json={'tag':'DELETE-TEST','description':'Retained equipment','assigned_to':'Standard'})
        self.assertEqual(r.status_code,200,r.text);asset_id=r.json()['id']
        target=next(u for u in self.client.get('/api/users').json() if u['username']=='standard')
        standard.put('/api/preferences',json={'mode':'dark','accent':'#123456'})
        r=self.client.request('DELETE','/api/users/'+str(target['id']),json={'username':'standard'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(standard.get('/api/me').status_code,401)
        self.assertFalse(any(u['username']=='standard' for u in self.client.get('/api/users').json()))
        asset=self.client.get('/api/assets/'+str(asset_id)).json()
        self.assertEqual(asset['assigned_to'],'Standard')
        self.assertTrue(any(h['actor']=='standard' and h['event']=='Created' for h in asset['history']))
        self.assertTrue(any(h['event']=='Deleted user' for h in self.client.get('/api/history').json()))
        with app.connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM sessions WHERE user_id=?',(target['id'],)).fetchone()[0],0)
            self.assertIsNone(c.execute('SELECT value FROM meta WHERE key=?',('appearance:'+str(target['id']),)).fetchone())
        self.assertEqual(self.client.request('DELETE','/api/users/'+str(target['id']),json={'username':'standard'}).status_code,404)
    def test_user_deletion_confirmation_and_permissions(self):
        readonly=self.add_user('readonly');standard=self.add_user('standard')
        target=next(u for u in self.client.get('/api/users').json() if u['username']=='readonly')
        url='/api/users/'+str(target['id']);body={'username':'readonly'}
        self.assertEqual(self.client.request('DELETE',url,json={'username':'wrong'}).status_code,400)
        self.assertEqual(standard.request('DELETE',url,json=body).status_code,403)
        self.assertEqual(readonly.request('DELETE',url,json=body).status_code,403)
        self.assertEqual(self.client.request('DELETE',url,json=body,headers={'X-CSRF-Token':'bad'}).status_code,403)
        guest=TestClient(app.app,base_url='http://127.0.0.1:8765')
        self.assertEqual(guest.request('DELETE',url,json=body).status_code,401)
        self.assertTrue(any(u['id']==target['id'] for u in self.client.get('/api/users').json()))
    def test_user_deletion_protects_admin_accounts(self):
        mine=next(u for u in self.client.get('/api/users').json() if u['username']=='matt')
        url='/api/users/'+str(mine['id'])
        self.assertEqual(self.client.request('DELETE',url,json={'username':'matt'}).status_code,400)
        other=self.add_user('admin')
        self.assertEqual(self.client.request('DELETE',url,json={'username':'matt'}).status_code,400)
        target=next(u for u in self.client.get('/api/users').json() if u['username']=='admin')
        self.assertEqual(self.client.request('DELETE','/api/users/'+str(target['id']),json={'username':'admin'}).status_code,200)
        self.assertEqual(other.get('/api/me').status_code,401)
        self.assertEqual(len(self.client.get('/api/users').json()),1)
    def test_password_change_revokes_sessions(self):
        other=self.login(TestClient(app.app,base_url='http://127.0.0.1:8765'))
        r=self.client.post('/api/password',json={'current':'A secure password 123','password':'My changed password 456'})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(other.get('/api/me').status_code,401)
        self.login(password='My changed password 456')

if __name__=='__main__':unittest.main(verbosity=2)
