"""Desktop application entry point; the server's lifetime follows its window."""
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request

PORT = 8766
URL = f'http://127.0.0.1:{PORT}'
IDENTITY = 'cmt-asset-manager'
MUTEX_NAME = 'Local\\CMTAssetManagerDesktop'

def occupied():
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', PORT)) == 0

def ready():
    # Bypass system HTTP proxies for this local-only application.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(URL + '/api/state', timeout=1) as response:
        return response.status == 200 and response.headers.get('X-CMT-Application') == IDENTITY

class InstanceGuard:
    def __init__(self):
        self.handle = None
    def acquire(self):
        if sys.platform != 'win32':
            return True
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            self.close()
            return False
        return True
    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

def start_server(port=PORT):
    from paths import data_directory
    data = data_directory()
    data.mkdir(parents=True, exist_ok=True)
    from recovery import apply_pending
    apply_pending(data)  # Must precede importing app, which opens/initializes SQLite.
    from app import app
    import uvicorn
    return uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
        loop='asyncio', http='h11', ws='none', access_log=False,
        log_config=None, log_level='warning'))

def configure_logging():
    from paths import data_directory
    folder = data_directory().parent / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / 'application.log', maxBytes=2_000_000,
                                 backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    # PyInstaller windowed builds have no stdout/stderr; preserve recovery messages.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    return folder

def activate_existing():
    if sys.platform != 'win32':
        return False
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    handle = user32.FindWindowW(None, 'CMT Asset Manager')
    if handle:
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, 9)
        user32.SetForegroundWindow(handle)
        return True
    return False


def desktop(recover=False):
    guard = InstanceGuard()
    try:
        logs = configure_logging()
        if not guard.acquire():
            if recover:
                raise RuntimeError('Close CMT Asset Manager before recovering an administrator account.')
            for _ in range(40):
                if activate_existing():
                    return 0
                time.sleep(.25)
            raise RuntimeError('CMT Asset Manager is starting or stopping. Please try again shortly.')
        if occupied():
            raise RuntimeError('Port 8766 is in use. Close the earlier CMT program before opening this version.')
        if recover:
            from PySide6.QtWidgets import QApplication
            from desktop import recover_admin
            application = QApplication.instance() or QApplication([])
            recover_admin()
            return 0
        from desktop import run_desktop
        return run_desktop(start_server, PORT, logs)
    except Exception as error:
        logging.exception('Desktop launch failed')
        if sys.platform == 'win32':
            ctypes.windll.user32.MessageBoxW(None, str(error), 'CMT Asset Manager', 0x10)
        else:
            print(str(error), file=sys.stderr)
        return 1
    finally:
        guard.close()


def main():
    if sys.platform == 'win32':
        from ctypes import wintypes
        shell = ctypes.WinDLL('shell32')
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
        shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        shell.SetCurrentProcessExplicitAppUserModelID('CyberMattTechnologies.CMTAssetManager')
    parser = argparse.ArgumentParser()
    parser.add_argument('--recover-admin', action='store_true')
    parser.add_argument('--smoke-server', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--desktop-check', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--data-dir', help=argparse.SUPPRESS)
    parser.add_argument('--smoke-port', type=int, default=PORT, help=argparse.SUPPRESS)
    args = parser.parse_args()
    checking = args.smoke_server or args.desktop_check
    if args.data_dir:
        if not checking:
            parser.error('--data-dir is only available for build validation')
        os.environ['CMT_DATA_DIR'] = str(Path(args.data_dir).resolve())
    if checking:
        if not args.data_dir or not 1024 <= args.smoke_port <= 65535:
            parser.error('Build checks require isolated data and a valid port')
        logs = configure_logging()
        if args.desktop_check:
            from desktop import run_desktop
            return run_desktop(start_server, args.smoke_port, logs, check=True)
        start_server(args.smoke_port).run()
        return 0
    return desktop(args.recover_admin)


if __name__ == '__main__':
    sys.exit(main())
