import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from admin_console import config  # noqa: E402
from admin_console.analytics import council, escalation, store  # noqa: E402

# Friday 2026-10-09 10:00 am Central - inside business hours, outside quiet hours.
NOW = "2026-10-09T15:00:00Z"

CRED_ENV = ("NTXP_GOOGLE_SA_KEY", "NTXP_GOOGLE_SA_EMAIL", "NTXP_GOOGLE_ADMIN_SUBJECT",
            "JOBTREAD_GRANT_KEY", "PLAUD_API_KEY", "QUO_API_KEY", "QUO_FROM_NUMBER",
            "ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
            "DEEPSEEK_API_KEY", "GLM_API_KEY", "NTXP_COUNCIL_URL", "QBO_ACCESS_TOKEN",
            "NTXP_ALISON_SMS", "NTXP_TREVOR_SMS", "NTXP_PROJECT_ASSIGNMENTS")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Demo mode, no credentials, a fresh JSON DB, clean hooks - for every test."""
    for k in CRED_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NTXP_ADMIN_DEMO", "1")
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setenv("NTXP_ADMIN_DB_PATH", str(tmp_path / "db.json"))
    prev = store.use_json(str(tmp_path / "db.json"))
    escalation.TRANSPORT.clear()
    escalation.OUTBOX.clear()
    council.PROVIDER_CALLS.clear()
    council.POST = None
    yield tmp_path
    store.use_backend(prev)
    escalation.TRANSPORT.clear()
    escalation.OUTBOX.clear()
    council.PROVIDER_CALLS.clear()
    council.POST = None


@pytest.fixture
def live(monkeypatch):
    """Switch demo mode off (still no credentials)."""
    monkeypatch.setenv("NTXP_ADMIN_DEMO", "")
    monkeypatch.setattr(config, "DEMO", False)
