import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store


@pytest.fixture(autouse=True)
def empty_store():
    # autouse=True runs this before every test, so tests never see each
    # other's data. Order of tests must not matter.
    store.clear()
    yield


@pytest.fixture
def client() -> TestClient:
    # TestClient calls the app directly, without starting a real server.
    return TestClient(app)
