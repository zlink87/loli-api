"""
Admin gating for the Story Batches endpoints.

There is no full RBAC in this service yet, so `require_admin` grants access when
EITHER of these holds:
  * the JWT carries an admin role claim (`role == "admin"` or
    `app_metadata.role == "admin"` — the Supabase-native way), or
  * the user's `sub` is in the ADMIN_USER_IDS config allowlist (works today with
    zero Supabase changes).
"""
from typing import Any, Dict

from fastapi import Depends, HTTPException, status

from auth.dependencies import get_current_user
from config import settings


def _is_admin(user: Dict[str, Any]) -> bool:
    sub = user.get("sub")
    if sub and sub in settings.admin_user_ids_list:
        return True
    if user.get("role") == "admin":
        return True
    app_meta = user.get("app_metadata") or {}
    if isinstance(app_meta, dict) and app_meta.get("role") == "admin":
        return True
    return False


async def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Dependency that allows only admin users through."""
    if not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
