"""
API Dependencies - Authentication and common dependencies
"""
from typing import Optional
from fastapi import Header, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from services.auth_service import verify_jwt_token

security = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[dict]:
    """
    Get current user if authenticated, None otherwise.
    Use this for endpoints that work both with and without auth.
    """
    if not credentials:
        return None

    user = verify_jwt_token(credentials.credentials)
    return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> dict:
    """
    Permissive single-user mode.
    If no bearer token is provided, fall back to a default user so that the
    frontend can work without the login flow.
    """
    if not credentials:
        # Fallback user for single-tenant deployments where auth is disabled
        return {"user_id": 1, "phone": "local", "exp": None}

    user = verify_jwt_token(credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return user


def require_auth():
    """Dependency that requires authentication"""
    return Depends(get_current_user)
