import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, security  # noqa: F401  (models registers the tables on Base)
from app.create_admin import create_or_promote_admin
from app.database import Base, get_db
from app.main import app
from app.payment_providers import FakeProvider, get_payment_provider

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    # Argon2 is slow ON PURPOSE, which makes a test suite that registers many
    # users crawl. In tests only, use the cheapest settings. The real settings
    # in app/security.py are untouched, and hashes still verify normally.
    monkeypatch.setattr(
        security, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )


@pytest.fixture
def session_factory():
    # "sqlite://" with no file name means a database that lives only in memory
    # and vanishes when the test ends. StaticPool keeps one connection, because
    # an in-memory database is destroyed if its connection closes.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


WEBHOOK_SECRET = "test-webhook-secret-for-the-fake-provider"


@pytest.fixture
def payment_provider() -> FakeProvider:
    # A fake payment company whose signing secret the tests know, so a test
    # can play the part of the provider and send correctly signed webhooks.
    return FakeProvider(WEBHOOK_SECRET)


@pytest.fixture
def plain_client(session_factory, payment_provider) -> TestClient:
    """A client that is not logged in."""

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    # Tell FastAPI: wherever a route asks for get_db, use the test database.
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_payment_provider] = lambda: payment_provider
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def register_and_login(client: TestClient, email: str, password: str = "correct horse battery") -> dict:
    """Create an account and return the headers that log requests in as it."""
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {login(client, email, password)}"}


@pytest.fixture
def alice(plain_client) -> dict:
    return register_and_login(plain_client, "alice@example.com")


@pytest.fixture
def bob(plain_client) -> dict:
    return register_and_login(plain_client, "bob@example.com")


@pytest.fixture
def admin(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def shop(plain_client, admin) -> dict:
    """A small shop: a notebook (19.99, 10 in stock) and a pen (1.50, 100)."""
    notebook = plain_client.post(
        "/products", json={"name": "Notebook", "price": "19.99", "stock": 10}, headers=admin
    ).json()
    pen = plain_client.post(
        "/products", json={"name": "Pen", "price": "1.50", "stock": 100}, headers=admin
    ).json()
    return {"notebook": notebook["id"], "pen": pen["id"]}


@pytest.fixture
def admin_token(plain_client, session_factory) -> str:
    with session_factory() as db:
        create_or_promote_admin(db, ADMIN_EMAIL, ADMIN_PASSWORD)
    return login(plain_client, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture
def admin_client(plain_client, admin_token) -> TestClient:
    """A client that is already logged in as an admin."""
    # A second client object sharing the same app and test database, with the
    # token attached to every request it makes.
    return TestClient(app, headers={"Authorization": f"Bearer {admin_token}"})
