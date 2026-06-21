"""Unit tests for the Jira client (HTTP mocked)."""
import jira_client

DIAG = {
    "root_cause": "NPE at StudentReportService.java:35 dereferenced a null enrollment. Extra detail here.",
    "fix_description": "null-check + 404",
    "files_changed": ["src/.../StudentReportService.java"],
    "test_passed": True,
    "confidence": 5,
}


def test_summary_derived_from_root_cause():
    s = jira_client._summary(DIAG)
    assert s.startswith("[Kure]")
    assert "StudentReportService.java:35" in s
    # only the first sentence is used
    assert "Extra detail" not in s


def test_summary_prefers_explicit_and_truncates():
    assert jira_client._summary({"summary": "explicit title"}) == "explicit title"
    long = {"summary": "x" * 300}
    assert len(jira_client._summary(long)) == 240


def test_summary_fallback_when_empty():
    assert jira_client._summary({}) == "[Kure] Production incident auto-detected"


def test_text_to_adf_structure():
    adf = jira_client.text_to_adf("para one\n\npara two")
    assert adf["type"] == "doc"
    assert len(adf["content"]) == 2
    assert adf["content"][0]["content"][0]["text"] == "para one"


def test_create_issue_uses_configured_type_and_dynamic_summary(monkeypatch):
    monkeypatch.setattr(jira_client, "JIRA_SITE", "https://x.atlassian.net")
    monkeypatch.setattr(jira_client, "JIRA_PROJECT_KEY", "KURE")
    monkeypatch.setattr(jira_client, "JIRA_ISSUE_TYPE", "Task")
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"key": "KURE-1"}

    def fake_post(url, auth, headers, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(jira_client.requests, "post", fake_post)
    key, url = jira_client.create_issue(DIAG)

    assert key == "KURE-1"
    assert url == "https://x.atlassian.net/browse/KURE-1"
    f = captured["payload"]["fields"]
    assert f["project"]["key"] == "KURE"
    assert f["issuetype"]["name"] == "Task"
    assert f["summary"].startswith("[Kure]")
    assert "kure" in f["labels"]
