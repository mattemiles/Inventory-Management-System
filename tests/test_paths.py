import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import data_directory

class PathTests(unittest.TestCase):
    def test_default_data_is_separate_from_installed_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}, clear=True):
                with patch.object(Path, 'home', side_effect=RuntimeError('Could not determine home directory.')) as home:
                    self.assertEqual(data_directory(), Path(folder)/'Cyber Matt Technologies'/'CMT Asset Manager'/'data')
                    home.assert_not_called()
    def test_home_fallback_when_local_app_data_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(Path, 'home', return_value=Path(folder)):
                    self.assertEqual(data_directory(), Path(folder)/'.local'/'share'/'Cyber Matt Technologies'/'CMT Asset Manager'/'data')
    def test_explicit_directory_supports_isolated_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'CMT_DATA_DIR': folder}, clear=True):
                self.assertEqual(data_directory(), Path(folder).resolve())
