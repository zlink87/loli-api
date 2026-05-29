"""
FastAPI security dependencies for authentication.

Primary auth is a Supabase-issued user JWT (verified with SUPABASE_JWT_SECRET),
so the frontends send the real signed-in user's token instead of minting one from
the old /debug/token endpoint. The internal HS256 JWT is kept as a fallback for
local development / service tokens.
"""
import logging
from typing import Dict, Any

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .jwt_handler import JWTHandler
from config import settings

logger = logging.getLogger(__name__)


def _decode_supabase_token(token: str) -> Dict[str, Any]:
    """Verify a Supabase-issued JWT. Raises ValueError on failure."""
    if not settings.SUPABASE_JWT_SECRET:
        raise ValueError("Supabase JWT verification not configured")
    try:
        return pyjwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=settings.SUPABASE_JWT_AUDIENCE or None,
        )
    except pyjwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except pyjwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")

# Security scheme for Swagger UI
security = HTTPBearer(
    scheme_name="JWT",
    description="Enter your JWT token"
)

# Singleton JWT handler instance
_jwt_handler: JWTHandler = None


def get_jwt_handler() -> JWTHandler:
    """Get or create JWT handler instance."""
    global _jwt_handler
    if _jwt_handler is None:
        _jwt_handler = JWTHandler(
            secret_key=settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
            access_token_expire_minutes=settings.JWT_EXPIRE_MINUTES
        )
    return _jwt_handler


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    jwt_handler: JWTHandler = Depends(get_jwt_handler)
) -> Dict[str, Any]:
    """
    Dependency to validate JWT and extract user info.

    Args:
        credentials: HTTP Bearer credentials from request
        jwt_handler: JWT handler instance

    Returns:
        Decoded token payload with user info

    Raises:
        HTTPException: If token is invalid or expired
    """
    token = credentials.credentials

    # Prefer Supabase token verification when configured; fall back to internal JWT.
    if settings.SUPABASE_JWT_SECRET:
        try:
            return _decode_supabase_token(token)
        except ValueError:
            pass  # fall through to internal handler (legacy/service tokens)

    try:
        payload = jwt_handler.decode_token(token)
        return payload
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(
        HTTPBearer(auto_error=False)
    ),
    jwt_handler: JWTHandler = Depends(get_jwt_handler)
) -> Dict[str, Any] | None:
    """
    Optional user authentication - doesn't fail if no token provided.

    Returns:
        Decoded token payload or None if no valid token
    """
    if credentials is None:
        return None

    if settings.SUPABASE_JWT_SECRET:
        try:
            return _decode_supabase_token(credentials.credentials)
        except ValueError:
            pass

    try:
        return jwt_handler.decode_token(credentials.credentials)
    except ValueError:
        return None


def create_test_token(user_id: str = "test_user") -> str:
    """
    Create a test token for development/testing.
    Only use in development mode!

    Args:
        user_id: User ID for the token

    Returns:
        JWT token string
    """
    handler = get_jwt_handler()
    return handler.create_access_token(subject=user_id)
