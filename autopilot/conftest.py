import os
import sys

# Make the autopilot/ modules (flat imports: log_reader, config, autopilot, ...)
# importable when running `python -m pytest` from this directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest


@pytest.fixture(autouse=True)
def _no_real_slack(monkeypatch):
    """Safety net: never post to real Slack during tests, even if the developer's
    .env has a live SLACK_WEBHOOK_URL / SLACK_BOT_TOKEN. Tests that specifically
    exercise Slack still monkeypatch these themselves."""
    try:
        import slack_client
        monkeypatch.setattr(slack_client, "SLACK_WEBHOOK_URL", "", raising=False)
        monkeypatch.setattr(slack_client, "SLACK_BOT_TOKEN", "", raising=False)
    except Exception:  # noqa: BLE001
        pass
    try:
        import slack_agent
        monkeypatch.setattr(slack_agent, "bridge_enabled", lambda: False, raising=False)
    except Exception:  # noqa: BLE001
        pass
