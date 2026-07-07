"""
Tests for admin gating (auth.admin.require_admin / _is_admin).

Runs under pytest or directly: python loli_api/tests/test_require_admin.py
"""
import asyncio

from fastapi import HTTPException

from config import settings
from auth.admin import _is_admin, require_admin


def test_allowlist_grants():
    settings.ADMIN_USER_IDS = "user-123,user-456"
    assert _is_admin({"sub": "user-123"}) is True
    assert _is_admin({"sub": "user-456"}) is True


def test_role_claim_grants():
    settings.ADMIN_USER_IDS = ""
    assert _is_admin({"sub": "z", "role": "admin"}) is True


def test_app_metadata_role_grants():
    settings.ADMIN_USER_IDS = ""
    assert _is_admin({"sub": "z", "app_metadata": {"role": "admin"}}) is True


def test_non_admin_denied():
    settings.ADMIN_USER_IDS = ""
    assert _is_admin({"sub": "nobody"}) is False


def test_require_admin_raises_403_for_non_admin():
    settings.ADMIN_USER_IDS = ""
    raised = False
    try:
        asyncio.run(require_admin(user={"sub": "nobody"}))
    except HTTPException as e:
        raised = e.status_code == 403
    assert raised


def test_require_admin_passes_admin_through():
    settings.ADMIN_USER_IDS = "admin-1"
    user = asyncio.run(require_admin(user={"sub": "admin-1"}))
    assert user["sub"] == "admin-1"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
