# CMT Asset Manager

**Version 1.1.2** — A local-first Windows inventory and asset management application from Cyber Matt Technologies.

CMT Asset Manager uses a Python/FastAPI backend, SQLite storage and a desktop interface built with PySide6 and web technologies. It runs locally, binds its web service to loopback only, and requires authentication. It does not require a cloud account.

## Features

- Equipment inventory, categories, assignments, and history
- Multiple user accounts and roles
- Image and document attachments, with photo previews and PDF viewing
- CSV import and Excel/CSV export
- Backup and restore
- Light/dark modes, appearance presets, and custom accent colors
- Packaged Windows desktop application with an offline-capable installer

## For users

The recommended Windows distribution is a compiled installer published under **Releases**. A release installer is **not included in this source repository**.

Once an installer is available, download it from the repository's Releases page and consult `USER_GUIDE.txt`. Your inventory data is stored under your Windows profile, separately from the installed application. Back up your existing data before upgrading.

## Build the Windows installer (maintainers)

1. Use a **Windows x64** PC with **Python 3.12 (64-bit)** and **Inno Setup 6.3 or newer** installed.
2. Download the repository source (or clone it) to a regular local folder.
3. Double-click `BUILD_INSTALLER.bat` from the project root. The build creates an isolated environment, runs validation, packages the application and compiles the installer; internet access is needed to install dependencies during the build.
4. Look under `output/` for `CMT_Asset_Manager_Setup_1.1.2.exe`, `SHA256SUMS.txt`, and `BUILD_INFO.json`.
5. Complete `WINDOWS_CHECKLIST.txt` on the final installer **before distributing it**.

Detailed instructions and migration notes are in `START_HERE.txt`; validation details are in `VALIDATION.md`.

## Project layout

| Path | Purpose |
| --- | --- |
| `app.py`, `paths.py`, `recovery.py`, `previews.py` | Backend and data-handling logic |
| `desktop.py`, `launcher.py`, `run.py` | Desktop integration and entry points |
| `static/` | Frontend HTML, CSS and JavaScript |
| `assets/` | Application icons and images |
| `tests/` | Automated tests |
| `tools/` | Build and smoke-test tooling |
| `installer/` | Inno Setup configuration |
| `USER_GUIDE.txt` | End-user instructions |

## Data and security

The repository intentionally excludes application databases, user accounts, photos, uploaded documents, backups and local secrets. **Never commit live data**, including files from your Windows user-profile application data folder. Run the packaged application's first-time setup to create your own administrator account.

## Licenses and third-party notices

See `QT_NOTICES.txt` and `licenses/` for the bundled Qt/PySide components' notices and license texts. **These third-party license files do not, by themselves, define the license for the CMT Asset Manager source code.** The project owner should choose and add a separate top-level `LICENSE` if public reuse, modification or redistribution of the application's source is intended.
