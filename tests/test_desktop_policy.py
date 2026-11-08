import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_policy import allowed_url

class DesktopPolicyTests(unittest.TestCase):
    def test_allows_local_inventory_and_document_resources(self):
        for url in ['http://127.0.0.1:8766/', 'http://127.0.0.1:8766/api/attachments/3',
                    'about:blank', 'blob:http://127.0.0.1:8766/id', 'chrome-extension://pdf-viewer/viewer.html',
                    'chrome://resources/cr_elements/cr_icon_button/cr_icon_button.js']:
            self.assertTrue(allowed_url(url, 8766), url)
    def test_blocks_external_and_local_file_navigation(self):
        for url in ['https://example.com', 'http://127.0.0.1:9999/', 'file:///C:/Windows/system.ini',
                    'javascript:alert(1)', 'chrome://settings', 'http://127.0.0.1:8766.evil.com/',
                    'http://user@127.0.0.1:8766/', 'http://127.0.0.1:bad/']:
            self.assertFalse(allowed_url(url, 8766), url)
