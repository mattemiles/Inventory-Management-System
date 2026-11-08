"""Resources are immutable; records belong to the current Windows profile."""
import os
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent

def data_directory():
    override = os.environ.get('CMT_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get('LOCALAPPDATA')
    base = Path(local_app_data) if local_app_data else Path.home() / '.local' / 'share'
    return base / 'Cyber Matt Technologies' / 'CMT Asset Manager' / 'data'
