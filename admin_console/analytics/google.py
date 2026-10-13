"""Google access for analytics. Every Google API call goes through
scripts/google_workspace/ntxp_google_access.service(...)."""

import os
import sys
from pathlib import Path

from admin_console import config

_REPO = Path(__file__).resolve().parents[2]
_ACCESS_DIR = _REPO / "scripts" / "google_workspace"
if str(_ACCESS_DIR) not in sys.path:
    sys.path.insert(0, str(_ACCESS_DIR))


def configured():
    has_key = bool(os.environ.get("NTXP_GOOGLE_SA_KEY") or os.environ.get("NTXP_GOOGLE_SA_EMAIL"))
    return has_key and bool(os.environ.get("NTXP_GOOGLE_ADMIN_SUBJECT"))


def demo():
    """Demo mode is explicit (NTXP_ADMIN_DEMO) or implied when nothing is configured."""
    return config.DEMO or os.environ.get("NTXP_ADMIN_DEMO", "").lower() in ("1", "true", "yes")


def live():
    return configured() and not demo()


def service(name, user=None, allow_write=False):
    import ntxp_google_access  # noqa: WPS433 - path inserted above
    return ntxp_google_access.service(name, user=user, allow_write=allow_write)
