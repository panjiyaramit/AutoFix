"""Unit tests for Phase 8 Slack notification (HTTP mocked)."""
import slack_client

DIAG_GREEN = {"root_cause": "null enrollment", "confidence": 5,
              "fix_applied": True, "test_passed": True}
DIAG_DIAGNOSE_ONLY = {"root_cause": "x", "confidence": 3}


def test_build_message_has_links_and_green_build():
    msg = slack_client.build_message(DIAG_GREEN, "AUTO-1",
                                     "https://j/AUTO-1", 7, "https://gh/pr/7")
    assert "<https://j/AUTO-1|AUTO-1>" in msg
    assert "<https://gh/pr/7|#7>" in msg
    assert "green" in msg
    assert "null enrollment" in msg


def test_build_message_diagnosis_only():
    msg = slack_client.build_message(DIAG_DIAGNOSE_ONLY, "AUTO-2",
                                     "https://j/AUTO-2", 0, "https://gh/pr/0")
    assert "Diagnosis only" in msg


def test_notify_demo_mode_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(slack_client, "SLACK_BOT_TOKEN", "")
    monkeypatch.setattr(slack_client, "SLACK_WEBHOOK_URL", "")
    assert slack_client.notify(DIAG_GREEN, "AUTO-1", "u", 1, "u") is False


def test_notify_bot_posts_to_configured_channel(monkeypatch):
    monkeypatch.setattr(slack_client, "SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(slack_client, "SLACK_CHANNEL", "#kure-notifications")
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"ok": True}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["channel"] = json["channel"]
        captured["text"] = json["text"]
        return FakeResp()

    monkeypatch.setattr(slack_client.requests, "post", fake_post)
    assert slack_client.notify(DIAG_GREEN, "AUTO-1", "https://j/AUTO-1", 7, "https://gh/pr/7") is True
    assert captured["url"].endswith("/chat.postMessage")
    assert captured["channel"] == "#kure-notifications"
    assert "AUTO-1" in captured["text"]


def test_notify_bot_returns_false_when_slack_says_not_ok(monkeypatch):
    monkeypatch.setattr(slack_client, "SLACK_BOT_TOKEN", "xoxb-test")

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"ok": False, "error": "channel_not_found"}

    monkeypatch.setattr(slack_client.requests, "post", lambda *a, **k: FakeResp())
    assert slack_client.notify(DIAG_GREEN, "AUTO-1", "u", 1, "u") is False


def test_notify_webhook_used_when_no_bot_token(monkeypatch):
    monkeypatch.setattr(slack_client, "SLACK_BOT_TOKEN", "")
    monkeypatch.setattr(slack_client, "SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass

    def fake_post(url, json, timeout):
        captured["url"] = url
        return FakeResp()

    monkeypatch.setattr(slack_client.requests, "post", fake_post)
    assert slack_client.notify(DIAG_GREEN, "AUTO-1", "u", 1, "u") is True
    assert captured["url"] == "https://hooks.slack.test/x"


def test_notify_never_raises_on_send_failure(monkeypatch):
    monkeypatch.setattr(slack_client, "SLACK_BOT_TOKEN", "xoxb-test")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(slack_client.requests, "post", boom)
    assert slack_client.notify(DIAG_GREEN, "AUTO-1", "u", 1, "u") is False


def test_build_working_message_mentions_detection_and_pending():
    msg = slack_client.build_working_message(
        {"exception_class": "java.lang.NullPointerException",
         "file": "StudentReportService.java", "line": "35"},
        "KR-1", "https://j/KR-1",
    )
    assert "detected" in msg.lower()
    assert "KR-1" in msg
    assert "NullPointerException" in msg
    assert "PR" in msg  # promises a PR to follow
