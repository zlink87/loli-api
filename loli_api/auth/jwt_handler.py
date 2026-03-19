"""
JWT token creation and validation handler.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
from pydantic import BaseModel


class TokenPayload(BaseModel):
    """JWT token payload structure."""
    sub: str  # Subject (user ID)
    exp: datetime  # Expiration
    iat: datetime  # Issued at
    type: str = "access"  # Token type


class JWTHandler:
    """Handles JWT creation and validation."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 60
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes

    def create_access_token(
        self,
        subject: str,
        expires_delta: Optional[timedelta] = None,
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new access token.

        Args:
            subject: The subject (user ID) for the token
            expires_delta: Optional custom expiration time
            additional_claims: Optional additional claims to include

        Returns:
            Encoded JWT token string
        """
        now = datetime.utcnow()
        expires = now + (expires_delta or timedelta(minutes=self.access_token_expire_minutes))

        payload = {
            "sub": subject,
            "exp": expires,
            "iat": now,
            "type": "access"
        }

        if additional_claims:
            payload.update(additional_claims)

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decode and validate a token.

        Args:
            token: The JWT token string

        Returns:
            Decoded payload as dictionary

        Raises:
            ValueError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {e}")

    def verify_token(self, token: str) -> bool:
        """
        Verify if a token is valid without returning payload.

        Args:
            token: The JWT token string

        Returns:
            True if valid, False otherwise
        """
        try:
            self.decode_token(token)
            return True
        except ValueError:
            return False

    def get_token_expiry(self, token: str) -> Optional[datetime]:
        """
        Get the expiration time of a token.

        Args:
            token: The JWT token string

        Returns:
            Expiration datetime or None if invalid
        """
        try:
            payload = self.decode_token(token)
            exp = payload.get("exp")
            if isinstance(exp, (int, float)):
                return datetime.fromtimestamp(exp)
            return None
        except ValueError:
            return None
