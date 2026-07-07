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


# Cached JWKS client for verifying Supabase asymmetric (ES256/RS256) tokens.
_jwks_client: "pyjwt.PyJWKClient | None" = None


def _get_jwks_client() -> "pyjwt.PyJWKClient":
    """Lazily build a cached PyJWKClient for the project's JWKS endpoint."""
    global _jwks_client
    if _jwks_client is None:
        jwks_url = settings.SUPABASE_URL.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        _jwks_client = pyjwt.PyJWKClient(jwks_url)
    return _jwks_client


def _decode_supabase_token(token: str) -> Dict[str, Any]:
    """Verify a Supabase-issued JWT. Raises ValueError on failure.

    Supports both signing schemes Supabase can issue:
      * HS256  — legacy symmetric shared secret (SUPABASE_JWT_SECRET)
      * ES256/RS256 — modern asymmetric "JWT signing keys", verified against the
        project's public JWKS at {SUPABASE_URL}/auth/v1/.well-known/jwks.json
    The scheme is selected from the token's own `alg` header.
    """
    aud = settings.SUPABASE_JWT_AUDIENCE or None
    try:
        alg = pyjwt.get_unverified_header(token).get("alg", "")

        if alg.startswith("ES") or alg.startswith("RS"):
            if not settings.SUPABASE_URL:
                raise ValueError(
                    "Supabase asymmetric JWT verification not configured (SUPABASE_URL unset)"
                )
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            return pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience=aud,
            )

        if not settings.SUPABASE_JWT_SECRET:
            raise ValueError("Supabase JWT verification not configured")
        return pyjwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=aud,
        )
    except pyjwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except pyjwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")
    except pyjwt.PyJWKClientError as e:
        raise ValueError(f"Supabase JWKS lookup failed: {e}")

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
    if settings.SUPABASE_JWT_SECRET or settings.SUPABASE_URL:
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

    if settings.SUPABASE_JWT_SECRET or settings.SUPABASE_URL:
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
