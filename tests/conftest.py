import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (registers the tables on Base)
from app.create_admin import create_or_promote_admin
from app.database import Base, get_db
from app.main import app

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct horse battery"


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


@pytest.fixture
def plain_client(session_factory) -> TestClient:
    """A client that is not logged in."""

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    # Tell FastAPI: wherever a route asks for get_db, use the test database.
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


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
