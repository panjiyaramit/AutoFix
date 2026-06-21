"""
slack_client.py — Phase 8: post an incident summary to Slack.

Sends a single message with the diagnosis, the build/test outcome, and links to
the Jira ticket and GitHub PR. Two delivery modes:

  1. Bot token (preferred — lets us target a named channel): set SLACK_BOT_TOKEN.
     The message is posted to SLACK_CHANNEL (default #autofix-notifications) via
     chat.postMessage. The bot must be a member of that channel.
  2. Incoming webhook: set SLACK_WEBHOOK_URL. The channel is fixed to whatever
     the webhook was created for (SLACK_CHANNEL is ignored in this mode).

If neither is configured it runs in demo mode (sends nothing) so the pipeline
stays runnable locally. A Slack failure never breaks the pipeline.
"""
from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "#autofix-notifications")


def has_direct_credentials() -> bool:
    """True when AutoFix can post to Slack directly (bot token or webhook configured)."""
    return bool(SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL)


def build_message(diagnosis: dict, jira_key: str, jira_url: str,
                  pr_number: int, pr_url: str) -> str:
    """Compose the Slack message text (mrkdwn)."""
    if diagnosis.get("fix_applied"):
        fix_line = "🛠️ Fix + regression test written — " + (
            "build *green* ✅" if diagnosis.get("test_passed") else "build *not green* ⚠ (needs review)"
        )
    else:
        fix_line = "🔎 Diagnosis only (no code change)"

    return (
        ":rotating_light: *AutoFix handled an incident*\n"
        f"*Root cause:* {diagnosis.get('root_cause', 'n/a')}\n"
        f"{fix_line}  ·  confidence {diagnosis.get('confidence', '?')}/5\n"
        f"*Jira:* <{jira_url}|{jira_key}>   *PR:* <{pr_url}|#{pr_number}>\n"
        "_A human still reviews and approves the PR — nothing auto-merges._"
    )


def build_working_message(incident: dict, jira_key: str, jira_url: str) -> str:
    """Early ping: incident detected + ticket filed, fix/test/PR still in progress."""
    loc = f"{incident.get('file', 'n/a')}:{incident.get('line', '?')}"
    return (
        ":rotating_light: *AutoFix detected an incident*\n"
        f"*Exception:* `{incident.get('exception_class', 'n/a')}` at `{loc}`\n"
        f"*Jira:* <{jira_url}|{jira_key}> _(created)_\n"
        ":hourglass_flowing_sand: AutoFix is now reading the code, writing a fix + "
        "regression test, and will open a draft PR. Final update to follow…"
    )


def post_text(text: str) -> bool:
    """Send a pre-built message via bot token or webhook. Never raises."""
    try:
        if SLACK_BOT_TOKEN:
            return _post_via_bot(text)
        if SLACK_WEBHOOK_URL:
            return _post_via_webhook(text)
        return False
    except Exception:  # noqa: BLE001 — a notification must never fail the pipeline
        return False


def notify_working(incident: dict, jira_key: str, jira_url: str) -> bool:
    """Post the early 'detected + working on it' message."""
    return post_text(build_working_message(incident, jira_key, jira_url))


def _post_via_bot(text: str) -> bool:
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": SLACK_CHANNEL, "text": text},
        timeout=15,
    )
    resp.raise_for_status()
    # Slack returns HTTP 200 even on logical errors; check the ok flag.
    return bool(resp.json().get("ok"))


def _post_via_webhook(text: str) -> bool:
    resp = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=15)
    resp.raise_for_status()
    return True


def notify(diagnosis: dict, jira_key: str, jira_url: str,
           pr_number: int, pr_url: str) -> bool:
    """
    Post the incident summary to Slack. Returns True if a message was sent,
    False in demo mode (no token/webhook) or on a send failure (Slack is
    best-effort and must never break the pipeline).
    """
    return post_text(build_message(diagnosis, jira_key, jira_url, pr_number, pr_url))
