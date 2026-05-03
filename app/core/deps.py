import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=True)
optional_bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_user(
    creds: HTTPAuthorizationCredentials,
    db: Session,
) -> User:
    exc = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(creds.credentials)
        user_id = payload["sub"]
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError):
        raise exc

    user = db.get(User, user_id)
    if user is None:
        raise exc
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    return _resolve_user(creds, db)


def get_current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(optional_bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if creds is None:
        return None
    return _resolve_user(creds, db)


def require_role(*allowed: UserRole):
    def checker(current: User = Depends(get_current_user)) -> User:
        if current.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Insufficient permissions"
            )
        return current

    return checker
