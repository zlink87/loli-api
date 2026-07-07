"""
Pytest configuration for the loli-api test suite.

Inserts the ``loli_api`` package directory onto ``sys.path`` (mirroring
main.py:22) so tests can import the app's modules with the same
``from services import ...`` / ``from models.enums import ...`` style the app
uses at runtime (main.py inserts loli_api/ into sys.path on startup).
"""
import sys
from pathlib import Path

# loli_api/tests/conftest.py -> loli_api/
_LOLI_API_DIR = Path(__file__).resolve().parent.parent
if str(_LOLI_API_DIR) not in sys.path:
    sys.path.insert(0, str(_LOLI_API_DIR))
