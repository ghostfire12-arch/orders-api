from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserRow
from app.security import decode_access_token
from app.user_repository import UserRepository


def get_user_repository(db: Annotated[Session, Depends(get_db)]) -> UserRepository:
    return UserRepository(db)


UserRepo = Annotated[UserRepository, Depends(get_user_repository)]

# Reads the header "Authorization: Bearer <token>". It also adds the green
# "Authorize" button to /docs, where you can paste a token to try routes.
# auto_error=False lets us send our own 401 message below.
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    users: UserRepo,
) -> UserRow:
    """Work out who is calling, from the token. 401 if we cannot tell."""
    if credentials is None:
        raise _unauthorized()
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise _unauthorized()
    # Check the user still exists. A token for a deleted account is useless.
    user = users.get_by_id(user_id)
    if user is None:
        raise _unauthorized()
    return user


CurrentUser = Annotated[UserRow, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> UserRow:
    """Allow admins only.

    401 means "we do not know who you are". 403 means "we know who you are,
    and you are not allowed". They are different problems.
    """
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
