# CMT Asset Manager

**Version 1.1.2 | Windows Inventory & Asset Management**

CMT Asset Manager is a local-first inventory and asset management application developed by **Cyber Matt Technologies**.

Designed for individuals, small businesses, and IT professionals, the application provides an easy way to track equipment, manage assignments, maintain asset records, and organize inventory without requiring cloud services or monthly subscriptions.

Built with Python, FastAPI, SQLite, PySide6, HTML, CSS, and JavaScript, CMT Asset Manager runs locally on Windows and provides a desktop interface.

## Download CMT Asset Manager

**Latest Release: v1.1.2**

[**Download CMT Asset Manager for Windows**](https://github.com/mattemiles/Inventory-Management-System/releases/latest)

The Windows installer is available under the **Assets** section of the latest release.

**Installation Instructions**

1. Download `CMT_Asset_Manager_Setup_1.1.2.exe`.
2. Run the installer on your Windows computer.
3. Follow the on-screen installation instructions.
4. Launch CMT Asset Manager.
5. Complete the initial administrator account setup.

No Python installation, cloud account, or external database server is required for the packaged Windows application.

**Note:** The installer is not digitally signed. Windows may display an unknown-publisher warning. Verify that the installer was downloaded from the official GitHub repository before installing.

## Features

### Inventory & Asset Tracking

- Create, edit, organize, and manage equipment records.
- Track asset assignments and equipment history.
- Organize inventory using categories.
- Attach equipment photographs and documents.
- View image previews and PDF attachments.

### User Management

- Multiple user accounts.
- Role-based access controls.
- Authentication required to access the application.
- Initial administrator account setup.

### Data Management

- Local SQLite database storage.
- CSV inventory import.
- Excel and CSV export.
- Backup and restore functionality.
- Inventory data stored separately from the application installation.

### Customization

- Light and dark appearance modes.
- Multiple color presets.
- Custom accent colors.
- Desktop interface with customizable appearance.

### Privacy & Local Operation

- Runs locally on your Windows computer.
- No cloud account required.
- No monthly subscription required.
- Local web service restricted to the loopback interface.
- Inventory records remain stored locally unless you choose to export or share them.

## System Requirements

- Windows 10 or Windows 11 (64-bit).
- Sufficient available storage for the application, attachments, and inventory database.
- Administrator permissions may be needed during installation.

The packaged installer includes the application dependencies needed for normal operation.

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12 / FastAPI |
| Database | SQLite |
| Desktop Interface | PySide6 |
| Frontend | HTML, CSS, JavaScript |
| Windows Packaging | PyInstaller |
| Windows Installer | Inno Setup |

## Project Structure

| Path | Purpose |
|---|---|
| `app.py` | Main application backend |
| `paths.py`, `recovery.py`, `previews.py` | Data handling and supporting functionality |
| `desktop.py`, `launcher.py`, `run.py` | Desktop application integration |
| `static/` | HTML, CSS, and JavaScript frontend |
| `assets/` | Application icons and graphics |
| `tests/` | Automated application tests |
| `tools/` | Build and validation utilities |
| `installer/` | Windows installer configuration |
| `USER_GUIDE.txt` | End-user instructions |
| `START_HERE.txt` | Developer setup and build information |
| `VALIDATION.md` | Build validation documentation |

## Building from Source

Developers can build CMT Asset Manager using the source code provided in this repository.

**Prerequisites**

- Windows 10 or Windows 11 (64-bit)
- Python 3.12 (64-bit)
- Inno Setup 6.3 or later

**Build Instructions**

1. Clone or download this repository.
2. Extract the source code if necessary.
3. Open the project directory.
4. Run `BUILD_INSTALLER.bat`.
5. Allow the build process to install dependencies, run validation, and package the application.
6. Locate the completed installer in the `output/` directory.

Internet connectivity is required during the dependency installation portion of the build.

See `START_HERE.txt`, `VALIDATION.md`, and `WINDOWS_CHECKLIST.txt` for additional information.

## Data Storage & Security

CMT Asset Manager stores inventory information locally under the Windows user profile, separately from the installed application.

The public source repository does not include actual user databases, account records, attachments, backups, or personal inventory data.

**Important recommendations:**

- Create regular inventory backups.
- Protect your Windows user account.
- Use strong passwords for application accounts.
- Verify backup integrity before performing significant upgrades.
- Never upload live inventory databases or sensitive attachments to public repositories.

## Releases & Version History

### Version 1.1.2 — Initial Public Release

- Windows desktop application.
- Asset and equipment tracking.
- Multi-user authentication and role management.
- Equipment assignments and history.
- File and image attachments.
- Backup and restore.
- CSV import and Excel/CSV export.
- Customizable themes and appearance settings.
- Windows installer distribution.

[View All Releases](https://github.com/mattemiles/Inventory-Management-System/releases)

## Licensing

Third-party Qt/PySide licensing information is available in `QT_NOTICES.txt` and the `licenses/` directory.

The application's own source-code licensing is governed by the top-level `LICENSE` file. Review that file before reusing, modifying, or redistributing the source.

## Developer

**Cyber Matt Technologies**

GitHub: [mattemiles](https://github.com/mattemiles)

---

*CMT Asset Manager — Local inventory management without the cloud.*
