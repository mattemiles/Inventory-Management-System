"""Dedicated desktop window with a shared, authenticated document profile."""
import json
import logging
from pathlib import Path
import queue
import secrets
import threading
import time
import shiboken6

from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QStackedWidget, QVBoxLayout, QWidget)
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
    QWebEngineSettings, QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from desktop_policy import allowed_url
from paths import RESOURCE_ROOT, data_directory

VERSION = '1.1.2'

class LocalRequests(QWebEngineUrlRequestInterceptor):
    def __init__(self, port, parent):
        super().__init__(parent)
        self.port = port
    def interceptRequest(self, info):
        if not allowed_url(info.requestUrl().toString(), self.port):
            info.block(True)

class LocalPage(QWebEnginePage):
    def __init__(self, profile, parent, port):
        super().__init__(profile, parent)
        self.port = port
    def acceptNavigationRequest(self, url, kind, main_frame):
        return allowed_url(url.toString(), self.port)

class DocumentWindow(QMainWindow):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowIcon(owner.windowIcon())
        self.setWindowTitle('Document — CMT Asset Manager')
        self.resize(1000, 780)
        self.view = owner.make_view(self)
        self.view.titleChanged.connect(lambda title: self.setWindowTitle((title or 'Document') + ' — CMT Asset Manager'))
        self.setCentralWidget(self.view)

class InventoryWindow(QMainWindow):
    def __init__(self, port, on_close, check=False):
        super().__init__()
        self.port, self.on_close, self.check = port, on_close, check
        self.documents, self.downloads, self.printers = [], {}, []
        self.forced_close = False
        self.setWindowTitle('CMT Asset Manager')
        self.setWindowIcon(QIcon(str(RESOURCE_ROOT / 'assets' / 'cmt.ico')))
        self.resize(1400, 900)
        self.setMinimumSize(960, 640)
        self.preferences = QSettings('Cyber Matt Technologies', 'CMT Asset Manager')
        self.last_native_theme = None
        self.native_theme({'dark': self.preferences.value('native/dark', False, type=bool),
                           'accent': self.preferences.value('native/accent', '#007f78'),
                           'ink': self.preferences.value('native/ink', '#ffffff'), 'persist': False})
        if not check:
            geometry = self.preferences.value('window/geometry')
            if geometry:
                self.restoreGeometry(geometry)
        profile_root = data_directory().parent / 'desktop-profile'
        profile_root.mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile('CMTDesktop', self)
        self.profile.setPersistentStoragePath(str(profile_root))
        self.profile.setCachePath(str(profile_root / 'cache'))
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.interceptor = LocalRequests(port, self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(self.download)
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)
        splash = QWidget()
        dark = self.preferences.value('native/dark', False, type=bool)
        splash.setStyleSheet('background:#101820;color:#edf3f7;' if dark else 'background:#f4f7f9;color:#152b3a;')
        layout = QVBoxLayout(splash)
        layout.addStretch()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(RESOURCE_ROOT / 'assets' / 'cmt.png')).scaled(92, 92, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        heading = QLabel('CMT Asset Manager')
        heading.setFont(QFont('Segoe UI', 25, QFont.Weight.DemiBold))
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        self.startup_label = QLabel('Opening your workspace…')
        self.startup_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.startup_label)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setFixedSize(220, 4)
        progress.setStyleSheet('QProgressBar{border:0;background:#dce5e8} QProgressBar::chunk{background:#007f78}')
        layout.addWidget(progress, alignment=Qt.AlignmentFlag.AlignHCenter)
        footer = QLabel('CYBER MATT TECHNOLOGIES')
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet('color:#647987;font-size:10px;margin-top:18px')
        layout.addWidget(footer)
        layout.addStretch()
        self.stack.addWidget(splash)
        self.view = self.make_view(self)
        self.stack.addWidget(self.view)
        file_menu = self.menuBar().addMenu('&File')
        file_menu.addAction('Open data folder', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_directory()))))
        file_menu.addAction('&Print…', lambda: self.print_view(self.view), QKeySequence('Ctrl+P'))
        file_menu.addSeparator()
        file_menu.addAction('E&xit', self.close, QKeySequence('Alt+F4'))
        view_menu = self.menuBar().addMenu('&View')
        view_menu.addAction('Refresh', self.view.reload, QKeySequence('Ctrl+R'))
        view_menu.addAction('Zoom in', lambda: self.zoom(.1), QKeySequence('Ctrl++'))
        view_menu.addAction('Zoom out', lambda: self.zoom(-.1), QKeySequence('Ctrl+-'))
        view_menu.addAction('Reset zoom', lambda: self.view.setZoomFactor(1), QKeySequence('Ctrl+0'))
        view_menu.addSeparator()
        view_menu.addAction('Full screen', lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen(), QKeySequence('F11'))
        help_menu = self.menuBar().addMenu('&Help')
        help_menu.addAction('About CMT Asset Manager', self.about)
        help_menu.addAction('Third-party notices', lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(RESOURCE_ROOT / 'third_party' / 'QT_NOTICES.txt'))))
        self.statusBar().hide()
        self.theme_timer = QTimer(self)
        self.theme_timer.timeout.connect(self.sync_native_theme)
        self.theme_timer.start(750)

    def sync_native_theme(self):
        self.view.page().runJavaScript("""(()=>{
          if(typeof appearance==='undefined')return '';
          return JSON.stringify({dark:appearance.mode==='dark'||(appearance.mode==='system'&&matchMedia('(prefers-color-scheme:dark)').matches),
          accent:appearance.accent,ink:getComputedStyle(document.documentElement).getPropertyValue('--accent-ink').trim(),
          persist:!document.querySelector('dialog[open]')});})()""", self.native_theme)

    def native_theme(self, value):
        try:
            theme = json.loads(value) if isinstance(value, str) else value
            if not isinstance(theme, dict):
                return
            dark, accent, ink = bool(theme['dark']), theme['accent'], theme['ink']
            key = (dark, accent, ink)
            if key != self.last_native_theme:
                palette = QPalette()
                for role, color in [(QPalette.ColorRole.Window, '#19242e' if dark else '#ffffff'),
                    (QPalette.ColorRole.WindowText, '#edf3f7' if dark else '#172b3b'),
                    (QPalette.ColorRole.Base, '#101820' if dark else '#ffffff'),
                    (QPalette.ColorRole.Text, '#edf3f7' if dark else '#172b3b'),
                    (QPalette.ColorRole.Button, '#22313e' if dark else '#eaf0f3'),
                    (QPalette.ColorRole.ButtonText, '#edf3f7' if dark else '#172b3b'),
                    (QPalette.ColorRole.Highlight, accent), (QPalette.ColorRole.HighlightedText, ink)]:
                    palette.setColor(role, QColor(color))
                QApplication.instance().setPalette(palette)
                self.last_native_theme = key
            if theme.get('persist') and not self.check:
                self.preferences.setValue('native/dark', dark)
                self.preferences.setValue('native/accent', accent)
                self.preferences.setValue('native/ink', ink)
        except (ValueError, KeyError, TypeError):
            return

    def make_view(self, parent):
        view = QWebEngineView(parent)
        page = LocalPage(self.profile, view, self.port)
        view.setPage(page)
        page.setBackgroundColor(QColor('#f4f7f9'))
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        page.newWindowRequested.connect(self.new_document)
        view.printRequested.connect(lambda: self.print_view(view))
        view.printFinished.connect(self.print_finished)
        page.windowCloseRequested.connect(parent.close if isinstance(parent, DocumentWindow) else self.close)
        return view

    def new_document(self, request):
        if not allowed_url(request.requestedUrl().toString(), self.port):
            return
        child = DocumentWindow(self)
        self.documents.append(child)
        child.destroyed.connect(lambda: self.documents.remove(child) if child in self.documents else None)
        request.openIn(child.view.page())
        child.show()

    def zoom(self, amount):
        self.view.setZoomFactor(max(.6, min(2, self.view.zoomFactor() + amount)))

    def about(self):
        box = QMessageBox(self)
        box.setWindowTitle('About CMT Asset Manager')
        box.setIconPixmap(QPixmap(str(RESOURCE_ROOT / 'assets' / 'cmt.png')).scaled(64, 64))
        box.setText(f'CMT Asset Manager {VERSION}')
        box.setInformativeText('Your equipment. Your workspace.\n\nCyber Matt Technologies\nLocal inventory with your data stored on this PC.\n\nQt/PySide and third-party notices are included with the application.')
        box.exec()

    def print_view(self, view):
        if self.printers:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QPrintDialog.DialogCode.Accepted:
            self.printers.append(printer)  # Must remain alive until asynchronous printing ends.
            view.print(printer)

    def print_finished(self, success):
        self.printers.clear()
        if not success and not self.check:
            QMessageBox.warning(self, 'Printing', 'The document could not be printed. Please try again.')

    def download(self, item):
        if not allowed_url(item.url().toString(), self.port):
            item.cancel()
            return
        filename = Path(item.suggestedFileName()).name or 'CMT_Download'
        if self.check:
            destination = data_directory().parent / 'checked-downloads' / filename
            destination.parent.mkdir(exist_ok=True)
        else:
            folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            selected, _ = QFileDialog.getSaveFileName(self, 'Save ' + filename, str(Path(folder) / filename))
            if not selected:
                item.cancel()
                return
            destination = Path(selected)
        item.setDownloadDirectory(str(destination.parent))
        item.setDownloadFileName(destination.name)
        self.downloads[item.id()] = item
        self.statusBar().show()
        self.statusBar().showMessage('Saving ' + filename + '…')
        item.isFinishedChanged.connect(lambda: self.download_finished(item, destination))
        item.accept()

    def download_finished(self, item, destination):
        if not item.isFinished():
            return
        self.downloads.pop(item.id(), None)
        if item.state() == item.DownloadState.DownloadCompleted:
            self.statusBar().showMessage('Saved ' + destination.name, 6000)
        else:
            self.statusBar().showMessage('Download did not finish.', 6000)
            if not self.check and not self.forced_close:
                QMessageBox.warning(self, 'Download', 'Could not save the file. ' + item.interruptReasonString())
        if not self.downloads:
            QTimer.singleShot(6500, self.statusBar().hide)

    def closeEvent(self, event):
        if (self.downloads or self.printers) and not self.forced_close:
            answer = QMessageBox.question(self, 'Finish current work?', 'A download or print job is still running. Close the application anyway?')
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.forced_close = True
        for item in list(self.downloads.values()):
            item.cancel()
        if not self.check:
            self.preferences.setValue('window/geometry', self.saveGeometry())
        for child in list(self.documents):
            child.close()
        self.on_close()
        event.accept()
        QApplication.instance().quit()

def recover_admin(parent=None):
    name, ok = QInputDialog.getText(parent, 'Recover administrator', 'Existing administrator username:')
    if not ok or not name.strip():
        return
    password, ok = QInputDialog.getText(parent, 'Recover administrator', 'New password (12–256 characters):', QLineEdit.EchoMode.Password)
    if not ok:
        return
    confirm, ok = QInputDialog.getText(parent, 'Recover administrator', 'Confirm new password:', QLineEdit.EchoMode.Password)
    if not ok:
        return
    if password != confirm:
        raise ValueError('Passwords do not match. No changes made.')
    from recovery import apply_pending
    apply_pending(data_directory())
    import app
    encoded = app.password_hash(password)
    with app.connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=? AND role='admin'", (name.strip(),)).fetchone()
        if not user:
            raise ValueError('Administrator not found. No account was created.')
        conn.execute('UPDATE users SET password=?,active=1 WHERE id=?', (encoded, user['id']))
        conn.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        conn.execute('DELETE FROM attempts WHERE username=?', (name.strip().lower(),))
        app.event(conn, {'username': '[local recovery]'}, 'Recovered administrator', user['username'])
    QMessageBox.information(parent, 'CMT Asset Manager', 'Password reset. Start CMT Asset Manager and sign in.')

def run_desktop(server_factory, port, logs, check=False):
    application = QApplication.instance() or QApplication([])
    application.setApplicationName('CMT Asset Manager')
    application.setOrganizationName('Cyber Matt Technologies')
    application.setApplicationVersion(VERSION)
    application.setFont(QFont('Segoe UI', 10))
    application.setQuitOnLastWindowClosed(False)
    errors = queue.Queue()
    state = {'server': None, 'loading': False, 'rendered': False, 'check_exit': 1}
    stopping = threading.Event()
    def worker():
        try:
            server = server_factory(port)
            state['server'] = server
            if not stopping.is_set():
                server.run()
        except BaseException as error:
            logging.exception('Desktop server failed')
            errors.put(str(error))
    thread = threading.Thread(target=worker, name='inventory-server', daemon=False)
    def stop():
        stopping.set()
        if state['server']:
            state['server'].should_exit = True
    window = InventoryWindow(port, stop, check)
    deadline = time.monotonic() + 90
    def fail(message):
        state['failure'] = True
        logging.error(message)
        if not check:
            QMessageBox.critical(window, 'CMT Asset Manager', message + '\n\nLog folder: ' + str(logs))
        window.forced_close = True
        window.close()
    def poll():
        if not errors.empty():
            fail(errors.get_nowait())
            return
        if not thread.is_alive() and not stopping.is_set():
            fail('The local workspace could not start.')
            return
        if not state['rendered'] and time.monotonic() > deadline:
            fail('The workspace did not become ready. Please restart the application.')
            return
        server = state['server']
        if server and server.started and not state['loading']:
            state['loading'] = True
            window.view.load(QUrl(f'http://127.0.0.1:{port}'))
        if state['loading'] and not state['rendered']:
            window.view.page().runJavaScript("Boolean(document.querySelector('#login-form,.app-shell'))", rendered)
    def rendered(result):
        if result and not state['rendered']:
            state['rendered'] = True
            window.stack.setCurrentWidget(window.view)
            if check:
                from desktop_check import DesktopCheck
                state['checker'] = DesktopCheck(window, lambda ok: finish_check(ok))
                state['checker'].start()
    def finish_check(ok):
        state['check_exit'] = 0 if ok else 1
        window.forced_close = True
        window.close()
    timer = QTimer(window)
    timer.timeout.connect(poll)
    timer.start(150)
    thread.start()
    window.show()
    try:
        application.exec()
    finally:
        timer.stop()
        window.theme_timer.stop()
        stop()
        thread.join()
        # Delete every page before its shared profile, including PDF windows.
        for page in window.findChildren(QWebEnginePage):
            shiboken6.delete(page)
        shiboken6.delete(window.profile)
    return state['check_exit'] if check else int(bool(state.get('failure')))
