from datetime import datetime, timedelta, timezone

import jwt

from app.config import JWT_ALGORITHM, SECRET_KEY
from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_is_argon2id_and_not_the_password():
    hashed = hash_password("correct horse battery")

    assert hashed.startswith("$argon2id$")
    assert "correct horse battery" not in hashed


def test_same_password_gives_different_hashes_because_of_the_salt():
    assert hash_password("same password") != hash_password("same password")


def test_verify_password():
    hashed = hash_password("correct horse battery")

    assert verify_password("correct horse battery", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_verify_password_with_a_garbage_hash_is_false_not_an_error():
    assert verify_password("anything", "not-a-hash") is False


def test_token_round_trip():
    assert decode_access_token(create_access_token(42)) == 42


def test_garbage_token_is_rejected():
    assert decode_access_token("not.a.token") is None


def test_token_signed_with_another_key_is_rejected():
    forged = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "an-attackers-guess-that-is-long-enough-to-sign",
        algorithm=JWT_ALGORITHM,
    )

    assert decode_access_token(forged) is None


def test_expired_token_is_rejected():
    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    assert decode_access_token(expired) is None


def test_token_without_expiry_is_rejected():
    no_expiry = jwt.encode({"sub": "1"}, SECRET_KEY, algorithm=JWT_ALGORITHM)

    assert decode_access_token(no_expiry) is None


def test_none_algorithm_attack_is_rejected():
    # The attacker removes the signature entirely and claims algorithm "none".
    # A careless server that trusts the token's own header would accept it.
    unsigned = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        key=None,
        algorithm="none",
    )

    assert decode_access_token(unsigned) is None
