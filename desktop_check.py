"""Run only against disposable build data; exercise the actual embedded engine."""
import base64
import json
import io
import logging
from pathlib import Path
import time
from PySide6.QtCore import QTimer
from paths import data_directory

def sample_pdf():
    parts = [b'%PDF-1.4\n']
    offsets = [0]
    stream = b'BT /F1 16 Tf 40 140 Td (CMT document check) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    for index, body in enumerate(objects, 1):
        offsets.append(sum(map(len, parts)))
        parts.append(str(index).encode() + b' 0 obj\n' + body + b'\nendobj\n')
    xref = sum(map(len, parts))
    parts.append(b'xref\n0 6\n0000000000 65535 f \n')
    parts += [f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:]]
    parts.append(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    return b''.join(parts)

class DesktopCheck:
    def __init__(self, window, finished):
        self.window, self.finished = window, finished
        self.deadline = time.monotonic() + 70
        self.timer = QTimer(window)
        self.timer.timeout.connect(self.poll)
        self.done = False
        self.pdf_verified = False
        self.pdf_focused = False

    def start(self):
        pdf = base64.b64encode(sample_pdf()).decode()
        from PIL import Image
        photo = io.BytesIO()
        with Image.new('RGB', (4000, 3000), '#245eea') as image:
            image.save(photo, format='JPEG', quality=90)
        photo64 = base64.b64encode(photo.getvalue()).decode()
        script = r'''
        window.__desktopCheck = {status:'running'};
        (async()=>{
          const wait=async fn=>{for(let i=0;i<120;i++){if(fn())return;await new Promise(r=>setTimeout(r,100))}throw Error('Desktop UI wait timed out')};
          const password='Disposable build password 123';
          for(const [id,value] of Object.entries({name:'Desktop check',username:'desktopcheck',password,confirm:password})){document.getElementById(id).value=value}
          document.getElementById('login-form').requestSubmit();
          await wait(()=>document.querySelector('.app-shell'));
          appearanceDialog();
          document.querySelector('#modal-body [data-mode="dark"]').click();
          document.querySelector('#modal-body [data-accent="#245eea"]').click();
          document.getElementById('modal-form').requestSubmit();
          await wait(()=>!document.getElementById('modal').open);
          if(document.documentElement.dataset.mode!=='dark')throw Error('Appearance did not apply');
          const a=await api('/assets',json('POST',{tag:'DESKTOP-001',description:'Desktop validation equipment',assigned_to:'Desktop user'}));
          const bytes=Uint8Array.from(atob('__PDF__'),c=>c.charCodeAt(0));
          let data=new FormData();data.append('kind','document');data.append('file',new File([bytes],'receipt.pdf',{type:'application/pdf'}));
          await api('/assets/'+a.id+'/attachments',{method:'POST',body:data});
          let picture=new FormData();picture.append('kind','photo');
          picture.append('file',new File([Uint8Array.from(atob('__PHOTO__'),c=>c.charCodeAt(0))],'equipment.jpg',{type:'image/jpeg'}));
          await api('/assets/'+a.id+'/attachments',{method:'POST',body:picture});
          await refresh();await showAsset(a.id);
          for(let i=0;i<3;i++){
            await showAsset(a.id);
            await wait(()=>{let img=document.querySelector('.equipment-hero-photo img');return img&&img.complete&&img.naturalWidth>0});
            let img=document.querySelector('.equipment-hero-photo img');
            if(img.naturalWidth>512||!img.src.endsWith('/preview'))throw Error('Equipment loaded the full original instead of a preview');
          }
          document.querySelector('.attachment-row a').click();
          document.querySelector('.equipment-hero-photo a').click();
          for(const path of ['/api/backup','/api/export.xlsx','/api/export.csv']){let link=document.createElement('a');link.href=path;document.body.appendChild(link);link.click();link.remove();await new Promise(r=>setTimeout(r,400))}
          window.__desktopCheck={status:'done',mode:document.documentElement.dataset.mode,pdf:true};
        })().catch(e=>window.__desktopCheck={status:'failed',error:String(e)});
        '''.replace('__PDF__', pdf).replace('__PHOTO__', photo64)
        self.window.view.page().runJavaScript(script)
        self.timer.start(300)

    def finish(self, success, message):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        logging.info('Desktop check: %s', message)
        report = data_directory().parent / 'DESKTOP_CHECK.json'
        report.write_text(json.dumps({'passed': success, 'message': message}), encoding='utf-8')
        self.finished(success)

    def poll(self):
        if time.monotonic() > self.deadline:
            self.finish(False, 'Embedded desktop check timed out')
            return
        self.window.view.page().runJavaScript('JSON.stringify(window.__desktopCheck||{})', self.inspect)

    def inspect(self, value):
        if self.done:
            return
        try:
            result = json.loads(value or '{}')
            if result.get('status') == 'failed':
                self.finish(False, result.get('error', 'JavaScript failed'))
            elif result.get('status') == 'done':
                folder = data_directory().parent / 'checked-downloads'
                files = list(folder.glob('*')) if folder.exists() else []
                if not {'.zip', '.xlsx', '.csv'}.issubset({p.suffix for p in files}) or self.window.downloads:
                    return
                if len(self.window.documents)<2:
                    return
                document = self.window.documents[0]
                if document.view.page().profile() != self.window.profile:
                    raise AssertionError('PDF viewer did not share the authenticated profile')
                if '/api/attachments/' not in document.view.url().toString():
                    return
                # The known fixture has a large white page. A blank gray PDF
                # window (for example, blocked engine resources) must fail.
                if not self.pdf_verified:
                    if not self.pdf_focused:
                        document.raise_()
                        document.activateWindow()
                        self.pdf_focused = True
                    image = document.view.grab().toImage()
                    samples = [image.pixelColor(x, y) for x in range(0, image.width(), 16)
                               for y in range(0, image.height(), 16)]
                    white = sum(c.red() > 240 and c.green() > 240 and c.blue() > 240 for c in samples)
                    if not samples or white < len(samples) * .04:
                        return
                    self.pdf_verified = True
                if not all(p.stat().st_size for p in files):
                    return
                picture = self.window.documents[1]
                if picture.view.page().profile() != self.window.profile:
                    raise AssertionError('Photo window did not share the authenticated profile')
                picture.view.page().runJavaScript('document.querySelector("img")?.naturalWidth||0', self.original_photo_loaded)
        except Exception as error:
            self.finish(False, str(error))

    def original_photo_loaded(self, width):
        if width == 4000:
            self.finish(True, 'Embedded login/theme, repeated thumbnail selection, full-resolution photo, PDF window and exports passed')
