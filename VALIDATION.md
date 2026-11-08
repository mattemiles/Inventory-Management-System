# CMT Asset Manager 1.1.2 desktop validation

Prepared November 1, 2026. The inventory now opens inside a dedicated Qt/PySide
desktop window. No browser tab, command prompt or separate control window is
part of normal operation. The application uses the same data path and installer
identity as version 1.1.0.

Completed in the Linux preparation environment with Python 3.12:

- 30 source checks cover backend authentication/roles, asset integrity,
  assignment, thumbnails/attachments/PDF headers, appearance, backup/recovery, data paths
  and embedded-window URL restrictions.
- Python and JavaScript source syntax checks.
- Real embedded Chromium rendering of first-run setup/login, the equipment
  interface, appearance saving, a separate authenticated PDF window, and
  downloads for backup, Excel and CSV. The PDF was visually inspected. The
  automatic desktop check also checks for the known fixture's rendered page,
  so a blank document window is a failure.
- Qt/PySide folder bundle built with PyInstaller, with both server and desktop
  checks executed against the preparation-platform bundle using temporary data.
- The theme integration follows light/dark mode and accent in native menus;
  prior geometry and the last saved native appearance are retained.

The preparation-platform bundle is not included in the deliverable. Windows
binaries must be built on Windows. BUILD_INSTALLER.bat installs dependencies,
runs source checks, builds the Windows EXE, runs backend and embedded-desktop
checks against that EXE, and only then invokes Inno Setup. The desktop check
opens a temporary window and closes it automatically; that is expected.

Windows installation, Windows title-bar behavior, Windows file/print dialogs,
shortcuts, taskbar activation, signed/unsigned reputation, clean offline use,
and upgrade/uninstall preservation still require the included Windows checklist.
The Linux headless QA process used development-only Chromium flags required by
its isolated environment; those flags are not set by the shipped application.
No independent security certification is claimed.

Photo loading update: the equipment hero/gallery request at most 512-pixel
previews, with an LRU cache bounded to 32 MiB / 128 items. Requests still require
a valid session even on a cache hit; the global no-store policy is retained.
Original upload bytes are unchanged. Camera EXIF orientation and transparent
PNGs are covered by regression checks, as are malformed legacy-image fallback
and deletion after caching. The embedded check reselects a photo three times
and checks the separate full-resolution photo window. No performance numbers
for the user’s Windows PC are inferred from the preparation environment.
