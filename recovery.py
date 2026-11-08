"""Validate and apply backups only while the server is stopped."""
import json, os, re, shutil, sqlite3, tempfile, zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

def validate_backup(path, destination=None):
    with zipfile.ZipFile(path) as z:
        infos=z.infolist(); names=[i.filename for i in infos]
        if len(names)!=len(set(names)) or len(names)>30000: raise ValueError('Duplicate or excessive archive entries.')
        if sum(i.file_size for i in infos)>2*1024**3: raise ValueError('Expanded archive exceeds 2 GB.')
        if 'manifest.json' not in names or 'inventory.sqlite3' not in names: raise ValueError('Required files are missing.')
        for i in infos:
            if i.filename not in ['manifest.json','inventory.sqlite3'] and not re.fullmatch(r'files/[a-f0-9]{48}\.(png|jpg|jpeg|gif|webp|pdf|txt|csv|docx|xlsx)',i.filename): raise ValueError('Unexpected archive path.')
            if (i.external_attr>>16)&0o170000==0o120000: raise ValueError('Links are not allowed.')
        manifest=json.loads(z.read('manifest.json'))
        if manifest.get('application')!='CMT Asset Manager' or manifest.get('schema')!=1: raise ValueError('Unsupported backup format.')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); z.extractall(root)
            db=root/'inventory.sqlite3'
            # Commit/rollback first, then close before copying or deleting files.
            with closing(sqlite3.connect(db)) as c, c:
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Database integrity check failed.')
                if c.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('Broken database relationships.')
                if c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()!=('1',): raise ValueError('Unsupported database schema.')
                required={'users':{'id','username','name','password','role','active','created'},'assets':{'id','tag','body','version','created','updated','deleted'},'sessions':{'token','user_id','csrf','created','last_seen'},'history':{'id','asset_id','actor','event','detail','created'},'attachments':{'id','asset_id','filename','stored','kind','size','created'},'lists':{'id','kind','value'},'attempts':{'username','count','until'}}
                for table, columns in required.items():
                    if not columns.issubset({r[1] for r in c.execute('PRAGMA table_info('+table+')')}): raise ValueError('Incomplete database schema.')
                if not c.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone(): raise ValueError('Backup needs an active administrator.')
                for stored,size in c.execute('SELECT stored,size FROM attachments'):
                    if not re.fullmatch(r'[a-f0-9]{48}\.(png|jpg|jpeg|gif|webp|pdf|txt|csv|docx|xlsx)',stored): raise ValueError('Invalid attachment path.')
                    p=root/'files'/stored
                    if not p.is_file() or p.stat().st_size!=size: raise ValueError('Missing or incomplete attachment.')
                for body, in c.execute('SELECT body FROM assets'):
                    if not isinstance(json.loads(body),dict): raise ValueError('Invalid asset record.')
                c.execute('DELETE FROM sessions'); c.execute('DELETE FROM attempts')
            if destination:
                dest=Path(destination); dest.mkdir(parents=True,exist_ok=True)
                shutil.copy2(db,dest/'inventory.sqlite3')
                shutil.copytree(root/'files',dest/'files',dirs_exist_ok=True) if (root/'files').exists() else (dest/'files').mkdir(exist_ok=True)

def apply_pending(data):
    data=Path(data); pending=data/'pending-restore.zip'
    journal=data/'restore-journal.json'
    # An interrupted swap is rolled back before attempting a new restore.
    if journal.exists():
        state=json.loads(journal.read_text()); safety=data/'safety'/state['snapshot']
        for name in ['inventory.sqlite3','files']:
            target=data/name
            if target.is_dir(): shutil.rmtree(target)
            elif target.exists(): target.unlink()
            source=safety/name
            if source.is_dir(): shutil.copytree(source,target)
            elif source.exists(): shutil.copy2(source,target)
        journal.unlink()
    if not pending.exists(): return
    with tempfile.TemporaryDirectory(dir=data,prefix='restore-') as tmp:
        validate_backup(pending,tmp)
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f'); safety=data/'safety'/stamp; safety.mkdir(parents=True)
        for name in ['inventory.sqlite3','files']:
            source=data/name
            if source.is_dir(): shutil.copytree(source,safety/name)
            elif source.exists(): shutil.copy2(source,safety/name)
        journal.write_text(json.dumps({'snapshot':stamp}))
        for name in ['inventory.sqlite3','files']:
            target=data/name
            if target.is_dir(): shutil.rmtree(target)
            elif target.exists(): target.unlink()
            shutil.move(str(Path(tmp)/name),str(target))
        pending.unlink(); journal.unlink()
        print('Backup restored. Previous data preserved in:',safety)
