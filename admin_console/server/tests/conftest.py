import pytest
from fastapi.testclient import TestClient

from admin_console import config
from admin_console.server import demo, gate
from admin_console.server.app import app

GOOGLE_ENV = ("NTXP_GOOGLE_SA_KEY", "NTXP_GOOGLE_SA_EMAIL", "NTXP_GOOGLE_ADMIN_SUBJECT",
              "NTXP_ADMIN_DB_SHEET_ID", "ANTHROPIC_API_KEY", "NTXP_PROJECT_NAMES")


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    for name in GOOGLE_ENV:
        monkeypatch.delenv(name, raising=False)
    demo.reset()
    gate.reset()
    yield
    demo.reset()
    gate.reset()


@pytest.fixture
def demo_mode(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)


@pytest.fixture
def client(demo_mode):
    return TestClient(app)


@pytest.fixture
def prod_client(monkeypatch):
    monkeypatch.setattr(config, "DEMO", False)
    return TestClient(app)
