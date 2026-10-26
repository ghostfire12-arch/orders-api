from datetime import datetime, timedelta, timezone

import jwt

from app.config import JWT_ALGORITHM, SECRET_KEY
from app.models import UserRow

CREDENTIALS = {"email": "ada@example.com", "password": "correct horse battery"}


def register(client, **overrides):
    return client.post("/auth/register", json={**CREDENTIALS, **overrides})


def login(client, **overrides):
    return client.post("/auth/login", json={**CREDENTIALS, **overrides})


def test_register_creates_an_account_without_leaking_secrets(plain_client):
    response = register(plain_client)

    assert response.status_code == 201
    body = response.json()
    assert body == {"id": 1, "email": "ada@example.com", "is_admin": False}
    assert "password" not in response.text
    assert "argon2" not in response.text


def test_password_is_stored_hashed(plain_client, session_factory):
    register(plain_client)

    with session_factory() as db:
        user = db.get(UserRow, 1)

    assert user.password_hash.startswith("$argon2id$")
    assert user.password_hash != CREDENTIALS["password"]


def test_email_is_normalized_to_lowercase(plain_client):
    response = register(plain_client, email="  Ada@Example.COM ")

    assert response.json()["email"] == "ada@example.com"


def test_duplicate_email_is_rejected_even_with_different_case(plain_client):
    register(plain_client)

    response = register(plain_client, email="ADA@example.com")

    assert response.status_code == 409


def test_short_password_is_rejected(plain_client):
    assert register(plain_client, password="short").status_code == 422


def test_enormous_password_is_rejected(plain_client):
    assert register(plain_client, password="x" * 129).status_code == 422


def test_invalid_email_is_rejected(plain_client):
    assert register(plain_client, email="not-an-email").status_code == 422
    assert register(plain_client, email="a b@example.com").status_code == 422


def test_users_cannot_make_themselves_admin(plain_client):
    # Extra fields are ignored, so is_admin in the request changes nothing.
    response = register(plain_client, is_admin=True)

    assert response.json()["is_admin"] is False


def test_login_returns_a_token(plain_client):
    register(plain_client)

    response = login(plain_client)

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_works_with_different_email_case(plain_client):
    register(plain_client)

    assert login(plain_client, email="ADA@example.com").status_code == 200


def test_wrong_password_and_unknown_email_give_the_same_error(plain_client):
    register(plain_client)

    wrong_password = login(plain_client, password="wrong password")
    unknown_email = login(plain_client, email="nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.headers["www-authenticate"] == "Bearer"


def test_me_returns_the_logged_in_user(plain_client):
    register(plain_client)
    token = login(plain_client).json()["access_token"]

    response = plain_client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"


def test_me_without_a_token_is_401(plain_client):
    assert plain_client.get("/users/me").status_code == 401


def test_me_with_a_garbage_token_is_401(plain_client):
    response = plain_client.get("/users/me", headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401


def test_me_with_an_expired_token_is_401(plain_client):
    register(plain_client)
    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    response = plain_client.get("/users/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


def test_token_for_a_deleted_user_is_401(plain_client, session_factory):
    register(plain_client)
    token = login(plain_client).json()["access_token"]
    with session_factory() as db:
        db.delete(db.get(UserRow, 1))
        db.commit()

    response = plain_client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_product_creation_needs_a_login(plain_client):
    response = plain_client.post("/products", json={"name": "Pen", "price": "1.50"})

    assert response.status_code == 401


def test_regular_users_cannot_create_products(plain_client):
    register(plain_client)
    token = login(plain_client).json()["access_token"]

    response = plain_client.post(
        "/products",
        json={"name": "Pen", "price": "1.50"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_admins_can_create_products(admin_client):
    response = admin_client.post("/products", json={"name": "Pen", "price": "1.50"})

    assert response.status_code == 201


def test_anyone_can_browse_products(admin_client, plain_client):
    admin_client.post("/products", json={"name": "Pen", "price": "1.50"})

    assert plain_client.get("/products").status_code == 200
    assert plain_client.get("/products/1").status_code == 200
