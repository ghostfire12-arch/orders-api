import pytest

from app.create_admin import create_or_promote_admin
from app.models import UserRow
from app.user_repository import UserRepository


def test_creates_a_new_admin(session_factory):
    with session_factory() as db:
        result = create_or_promote_admin(db, "boss@example.com", "correct horse battery")
        user = UserRepository(db).get_by_email("boss@example.com")

    assert result == "created"
    assert user.is_admin is True


def test_promotes_an_existing_user_without_touching_the_password(session_factory):
    with session_factory() as db:
        users = UserRepository(db)
        original = users.add("ada@example.com", "$argon2id$original-hash")

        result = create_or_promote_admin(db, "ada@example.com", None)
        promoted = db.get(UserRow, original.id)

    assert result == "promoted"
    assert promoted.is_admin is True
    assert promoted.password_hash == "$argon2id$original-hash"


def test_creating_without_a_password_fails(session_factory):
    with session_factory() as db:
        with pytest.raises(ValueError):
            create_or_promote_admin(db, "new@example.com", None)
