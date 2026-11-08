# Build only on Windows using a dedicated build environment.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'static'), 'static'), (str(root / 'assets'), 'assets'),
         (str(root / 'third_party'), 'third_party')]
for name in ('fastapi', 'uvicorn', 'python-multipart', 'opentelemetry-api', 'PySide6', 'Pillow'):
    datas += copy_metadata(name, recursive=True)
a = Analysis([str(root / 'launcher.py')], pathex=[str(root)],
             binaries=[], datas=datas,
             hiddenimports=collect_submodules('uvicorn') + ['app', 'recovery', 'paths', 'desktop', 'desktop_check', 'desktop_policy'],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['pytest', 'unittest', 'httpx', 'tkinter', 'PyQt5', 'PyQt6', 'PySide2'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='CMTAssetManager',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(root / 'assets' / 'cmt.ico'),
          version=str(root / 'installer' / 'version_info.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='CMTAssetManager')
