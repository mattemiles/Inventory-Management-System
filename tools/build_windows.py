"""Build, validate, and package on the publisher's Windows PC."""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    print('\n>', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)

def find_compiler():
    override = os.environ.get('CMT_ISCC')
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
        raise RuntimeError('CMT_ISCC does not point to ISCC.exe')
    found = shutil.which('ISCC.exe')
    if found:
        return Path(found)
    for base in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        value = os.environ.get(base)
        if value:
            for folder in ('Inno Setup 7', 'Inno Setup 6', 'Programs/Inno Setup 7', 'Programs/Inno Setup 6'):
                candidate = Path(value) / folder / 'ISCC.exe'
                if candidate.is_file():
                    return candidate
    raise RuntimeError('Install Inno Setup 6.3 or newer from https://jrsoftware.org/isdl.php, then run this build again.')

def collect_notices():
    dest = ROOT / 'third_party'
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir()
    inventory = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = dist.metadata['Name']
        folder = dest / name
        folder.mkdir(exist_ok=True)
        info = {'name': name, 'version': dist.version,
                'license': dist.metadata.get('License-Expression') or dist.metadata.get('License'),
                'project_urls': dist.metadata.get_all('Project-URL') or []}
        inventory.append(info)
        for item in dist.files or []:
            if any(word in item.name.upper() for word in ('LICENSE', 'COPYING', 'NOTICE')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = folder / str(item).replace('\\', '_').replace('/', '_')
                    shutil.copy2(source, target)
        (folder / 'PACKAGE.txt').write_text(json.dumps(info, indent=2), encoding='utf-8')
    license_path = Path(sys.base_prefix) / 'LICENSE.txt'
    if not license_path.is_file():
        raise RuntimeError('Python LICENSE.txt was not found in the standard Python installation.')
    shutil.copy2(license_path, dest / 'PYTHON_LICENSE.txt')
    (dest / 'PACKAGES.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    shutil.copytree(ROOT / 'licenses', dest / 'licenses', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'QT_NOTICES.txt', dest / 'QT_NOTICES.txt')

def main():
    if (sys.platform != 'win32' or struct.calcsize('P') != 8
            or platform.machine().lower() not in ('amd64', 'x86_64')
            or sys.version_info[:2] != (3, 12)):
        raise RuntimeError('Build with 64-bit Python 3.12 on Windows.')
    compiler = find_compiler()
    # Avoid an old installer being mistaken for a successful new build.
    output = ROOT / 'output'
    output.mkdir(exist_ok=True)
    setup = output / 'CMT_Asset_Manager_Setup_1.1.2.exe'
    setup.unlink(missing_ok=True)
    for filename in ('SHA256SUMS.txt', 'BUILD_INFO.json'):
        (output / filename).unlink(missing_ok=True)
    run(sys.executable, '-m', 'pip', 'install', '-r', 'requirements-dev.txt', 'pyinstaller==6.22.3')
    run(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q')
    collect_notices()
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', 'CMTAssetManager.spec')
    run(sys.executable, 'tools/smoke_windows.py', ROOT / 'dist/CMTAssetManager/CMTAssetManager.exe')
    run(sys.executable, 'tools/smoke_desktop.py', ROOT / 'dist/CMTAssetManager/CMTAssetManager.exe')
    run(compiler, ROOT / 'installer/CMT_Asset_Manager.iss')
    if not setup.is_file():
        raise RuntimeError('The compiler did not produce the expected setup file.')
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(digest + '  ' + setup.name + '\n', encoding='ascii')
    (output / 'BUILD_INFO.json').write_text(json.dumps({
        'version': '1.1.2', 'python': sys.version, 'platform': platform.platform(),
        'pyinstaller': metadata.version('pyinstaller'), 'installer_sha256': digest,
        'automated_checks': 'passed', 'native_manual_checklist': 'required before publication',
        'compiler': str(compiler)}, indent=2), encoding='utf-8')
    source_zip = output / 'CMT_Asset_Manager_1.1.2_Source.zip'
    excluded = {'build','dist','output','third_party','__pycache__','.build-venv','data'}
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob('*')):
            if path.is_file() and not any(part in excluded for part in path.relative_to(ROOT).parts):
                archive.write(path, Path('CMT_Asset_Manager') / path.relative_to(ROOT))
    print('\nCreated:', setup)
    print('Source and notices:', source_zip)

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('\nBUILD FAILED:', error, file=sys.stderr)
        sys.exit(1)
