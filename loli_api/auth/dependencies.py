"""
FastAPI security dependencies for authentication.
"""
from typing import Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .jwt_handler import JWTHandler
from config import settings

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
