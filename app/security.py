from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import ACCESS_TOKEN_MINUTES, JWT_ALGORITHM, SECRET_KEY

# Argon2id is the algorithm recommended for storing passwords. It is
# deliberately slow and memory-hungry, so guessing millions of passwords per
# second becomes impractical for an attacker who steals the database.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    # The result looks like "$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>".
    # A random salt is generated every time, so two users with the same
    # password get different hashes, and the settings are stored inside the
    # string so old hashes keep working if we change the settings later.
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        # Wrong password, or the stored value is not a valid hash.
        return False


# Used to keep login timing the same when an email does not exist. See login.
DUMMY_HASH = _hasher.hash("this is not a real password")


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),  # subject: who this token is for
        "iat": now,  # issued at
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),  # expires at
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Return the user id inside a valid token, or None for any problem."""
    try:
        claims = jwt.decode(
            token,
            SECRET_KEY,
            # Only accept the algorithm we use. Never read it from the token.
            algorithms=[JWT_ALGORITHM],
            # A token without an expiry or a subject is rejected.
            options={"require": ["exp", "sub"]},
        )
        return int(claims["sub"])
    except (jwt.InvalidTokenError, ValueError):
        # Bad signature, expired, malformed, missing claims, or a non-number id.
        return None
