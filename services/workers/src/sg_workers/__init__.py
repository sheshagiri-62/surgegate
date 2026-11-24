"""SurgeGate background workers (hold timer, tickets).

Vendored pure-Python dependencies (pg8000, segno, ...) live in _vendor/ and are put on sys.path
here, before any module of the package imports them.
"""

import sys
from pathlib import Path

_VENDOR = str(Path(__file__).resolve().parent / "_vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
