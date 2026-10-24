import os
from pathlib import Path


def _path_env(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


FONT_ROOT = _path_env('FONT_ROOT', '/data/fonts')
STATE_DIR = _path_env('STATE_DIR', '/data/state')
RECYCLE_DIR = _path_env('RECYCLE_DIR', '/data/recycle')
CONFIG_DIR = _path_env('CONFIG_DIR', str(STATE_DIR / 'config'))
CONFIG_FILE = CONFIG_DIR / 'settings.json'
DB_PATH = STATE_DIR / 'fonts.db'
STATIC_DIR = Path(__file__).resolve().parent / 'static'

DEFAULT_EXTENSIONS = {'.ttf', '.otf', '.ttc', '.woff', '.woff2'}
_ext_env = os.environ.get('SCAN_EXTENSIONS', '')
SCAN_EXTENSIONS = {
    ('.' + item.strip().lower().lstrip('.'))
    for item in _ext_env.split(',')
    if item.strip()
} or DEFAULT_EXTENSIONS

AUTO_SCAN = os.environ.get('AUTO_SCAN', '1').lower() not in {'0', 'false', 'no'}
PAGE_SIZE_DEFAULT = 100
PAGE_SIZE_MAX = 500
