"""Launch the final desktop executable in an isolated Windows workspace."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

def main():
    executable = Path(sys.argv[1]).resolve()
    command = [sys.executable, str(executable)] if executable.suffix == '.py' else [str(executable)]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='cmt-desktop-check-') as folder:
        try:
            result = subprocess.run(command + ['--desktop-check', '--data-dir', str(Path(folder)/'data'),
                '--smoke-port', str(port)], timeout=180)
            report_path = Path(folder)/'DESKTOP_CHECK.json'
            report = json.loads(report_path.read_text()) if report_path.exists() else {}
            if result.returncode or not report.get('passed'):
                log = Path(folder)/'logs/application.log'
                detail = log.read_text(encoding='utf-8')[-7000:] if log.exists() else 'No application log was produced.'
                raise RuntimeError(f'Desktop check failed: {report}\n{detail}')
            print(report['message'])
        except subprocess.TimeoutExpired:
            raise RuntimeError('The desktop executable did not finish validation in 180 seconds.')

if __name__ == '__main__':
    main()
