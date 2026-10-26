from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUser, UserRepo
from app.schemas import LoginRequest, Token, UserCreate, UserPublic
from app.security import DUMMY_HASH, create_access_token, hash_password, verify_password
from app.user_repository import EmailAlreadyRegistered

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, users: UserRepo) -> UserPublic:
    try:
        # We hash the password here. The plain password is never saved,
        # logged, or returned. response_model=UserPublic also guarantees the
        # hash cannot leak, because that model has no such field.
        user = users.add(email=payload.email, password_hash=hash_password(payload.password))
    except EmailAlreadyRegistered:
        # 409 Conflict. Tradeoff: this reveals that an email has an account.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from None
    return UserPublic.model_validate(user)


@router.post("/auth/login", response_model=Token)
def login(payload: LoginRequest, users: UserRepo) -> Token:
    user = users.get_by_email(payload.email)

    # Always run one hash check, even when the email is unknown. Otherwise
    # unknown emails answer instantly and real ones answer slowly, and an
    # attacker can use that timing difference to discover who has an account.
    stored_hash = user.password_hash if user else DUMMY_HASH
    password_ok = verify_password(payload.password, stored_hash)

    if user is None or not password_ok:
        # One message for both cases, so the error never says which part was
        # wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id))


@router.get("/users/me", response_model=UserPublic)
def read_me(user: CurrentUser) -> UserPublic:
    # CurrentUser runs the whole token check before this function starts.
    return UserPublic.model_validate(user)
