"""Exercise the actual bundled EXE against disposable data, never live records."""
import base64
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

def multipart(fields, filename, content):
    boundary = 'CMT' + secrets.token_hex(20)
    chunks = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
    chunks += [content, f'\r\n--{boundary}--\r\n'.encode()]
    return b''.join(chunks), 'multipart/form-data; boundary=' + boundary

def main():
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise RuntimeError('Application executable was not found.')
    # A source mode is useful for validating the same launcher before freezing.
    command = [sys.executable, str(executable)] if executable.suffix == '.py' else [str(executable)]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory(prefix='cmt-build-check-') as temp:
        data = Path(temp) / 'data'
        process = None
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        csrf = ''
        password = secrets.token_urlsafe(24)
        def request(path, body=None, method='GET', content_type='application/json', expected=200):
            headers = {'Content-Type': content_type, 'X-CSRF-Token': csrf}
            if body is not None and isinstance(body, dict):
                body = json.dumps(body).encode()
            req = urllib.request.Request(url + path, data=body, method=method, headers=headers)
            try:
                response = opener.open(req, timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                payload = response.read()
                assert response.status == expected, (path, response.status, payload[:500])
                return payload, response.headers
        def obj(path, body=None, method='GET'):
            return json.loads(request(path, body, method)[0])
        def launch():
            nonlocal process
            env = os.environ.copy()
            env.pop('CMT_DATA_DIR', None)
            process = subprocess.Popen(command + ['--smoke-server', '--data-dir', str(data), '--smoke-port', str(port)],
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'Bundled application exited early ({process.returncode}). Logs: {Path(temp)/"logs"}')
                try:
                    payload, headers = request('/api/state')
                    if headers.get('X-CMT-Application') == 'cmt-asset-manager':
                        return json.loads(payload)
                except (OSError, AssertionError):
                    pass
                time.sleep(.25)
            raise RuntimeError('Bundled application did not become ready within 60 seconds.')
        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                process = None
        def login():
            nonlocal csrf
            csrf = obj('/api/login', {'username': 'buildadmin', 'password': password}, 'POST')['csrf']
        try:
            assert launch()['setup'] is True
            request('/api/assets', expected=401)
            html = request('/')[0]
            assert b'CMT Asset Manager' in html
            for path in ['/static/app.js', '/static/style.css', '/static/appearance-startup.js']:
                assert request(path)[0]
            obj('/api/setup', {'username': 'buildadmin', 'name': 'Build validation', 'password': password}, 'POST')
            login()
            assert obj('/api/settings')['data_directory'] == str(data.resolve())
            assert obj('/api/settings')['version'] == '1.1.2'
            a = obj('/api/assets', {'tag': 'BUILD-001', 'description': 'Disposable validation equipment', 'assigned_to': 'Build user'}, 'POST')
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9x8AAAAASUVORK5CYII=')
            pdf = b'%PDF-1.4\n%%EOF'
            for filename, content, kind in [('photo.png', png, 'photo'), ('receipt.PDF', pdf, 'document'), ('note.txt', b'Note', 'document')]:
                body, ctype = multipart({'kind': kind}, filename, content)
                request(f"/api/assets/{a['id']}/attachments", body, 'POST', ctype)
            detail = obj('/api/assets/' + str(a['id']))
            assert detail['assigned_to'] == 'Build user'
            for item in detail['attachments']:
                raw, headers = request('/api/attachments/' + str(item['id']))
                if item['filename'].lower().endswith('.pdf'):
                    assert raw == pdf and headers['Content-Type'] == 'application/pdf'
                    assert headers['Content-Disposition'].startswith('inline;')
                elif item['filename'].endswith('.txt'):
                    assert headers['Content-Disposition'].startswith('attachment;')
                else:
                    assert raw == png
            prefs = {'mode': 'dark', 'accent': '#245eea'}
            obj('/api/preferences', prefs, 'PUT')
            assert obj('/api/preferences') == prefs
            backup = request('/api/backup')[0]
            assert backup.startswith(b'PK')
            obj('/api/assets', {'tag': 'AFTER-BACKUP', 'description': 'Should disappear after restore'}, 'POST')
            body, ctype = multipart({'password': password}, 'backup.zip', backup)
            request('/api/restore', body, 'POST', ctype)
            stop()
            jar.clear()
            csrf = ''
            assert launch()['setup'] is False
            request('/api/assets', expected=401)
            login()
            records = obj('/api/assets')
            assert len(records) == 1 and records[0]['tag'] == 'BUILD-001'
            assert len(obj('/api/assets/' + str(a['id']))['attachments']) == 3
            assert obj('/api/preferences') == prefs
            assert list((data / 'safety').iterdir())
            assert not (data / 'pending-restore.zip').exists()
            print('Application smoke checks: setup, login, static resources, assignment, attachments, PDF, preferences, backup, restart and restore passed.')
        finally:
            stop()

if __name__ == '__main__':
    main()
