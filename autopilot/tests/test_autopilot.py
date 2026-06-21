"""Unit + integration tests for the orchestrator wiring (Phase 3)."""
import autopilot

SAMPLE_INCIDENT = {
    "timestamp": "2026-06-02 09:16:05",
    "logger": "c.e.s.e.GlobalExceptionHandler",
    "header_message": "Unhandled exception. Request params: studentId=4271, academicYear=2023-24",
    "student_id": "4271",
    "academic_year": "2023-24",
    "exception_class": "java.lang.NullPointerException",
    "exception_message": 'Cannot invoke getGradeLevel() because "enrollment" is null',
    "file": "StudentReportService.java",
    "line": "35",
    "traceback": "java.lang.NullPointerException: ...\n\tat ...generateReport(StudentReportService.java:35)",
}

DIAGNOSIS = {"root_cause": "rc", "files_changed": [], "fix_description": "fd", "confidence": 4}
FIX_RESULT = {**DIAGNOSIS, "test_added": "t", "test_passed": True,
              "fix_applied": True, "source": "agent-sdk"}


def test_create_jira_demo_mode_when_no_creds(monkeypatch):
    monkeypatch.delenv("JIRA_SITE", raising=False)
    monkeypatch.delenv("JIRA_TOKEN", raising=False)
    key, url = autopilot.create_jira(SAMPLE_INCIDENT)
    assert key == "AUTO-DEMO"
    assert "AUTO-DEMO" in url


def test_create_jira_opens_incident_ticket_when_creds_present(monkeypatch):
    # create_jira now does PHASE 1: open from the incident, before the fix exists.
    monkeypatch.setenv("JIRA_SITE", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_TOKEN", "tok")
    monkeypatch.setenv("JIRA_EMAIL", "a@b.com")
    import jira_client
    called = {}

    def fake_create_incident_issue(incident):
        called["incident"] = incident
        return "REAL-1", "https://x.atlassian.net/browse/REAL-1"

    monkeypatch.setattr(jira_client, "create_incident_issue", fake_create_incident_issue)
    key, url = autopilot.create_jira(SAMPLE_INCIDENT)
    assert key == "REAL-1"
    assert called["incident"] is SAMPLE_INCIDENT


def test_update_jira_enriches_with_diagnosis(monkeypatch):
    # PHASE 2: after the fix, update_jira pushes the full diagnosis + PR link.
    monkeypatch.setenv("JIRA_SITE", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_TOKEN", "tok")
    import jira_client
    called = {}

    def fake_update(key, diagnosis, pr_url):
        called["args"] = (key, diagnosis, pr_url)

    monkeypatch.setattr(jira_client, "update_with_diagnosis", fake_update)
    autopilot.update_jira("REAL-1", FIX_RESULT, "https://gh/pr/7")
    assert called["args"] == ("REAL-1", FIX_RESULT, "https://gh/pr/7")


def test_update_jira_skips_mock_ticket(monkeypatch):
    # Must NOT try to update the mock AUTO-DEMO ticket.
    monkeypatch.setenv("JIRA_SITE", "https://x.atlassian.net")
    monkeypatch.setenv("JIRA_TOKEN", "tok")
    import jira_client
    called = {"hit": False}
    monkeypatch.setattr(jira_client, "update_with_diagnosis",
                        lambda *a, **k: called.__setitem__("hit", True))
    autopilot.update_jira("AUTO-DEMO", FIX_RESULT, "url")
    assert called["hit"] is False


def test_open_pr_demo_mode_when_no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    num, url = autopilot.open_pr(DIAGNOSIS, "AUTO-DEMO")
    assert num == 0
    assert "pull/0" in url


def test_open_pr_demo_mode_with_placeholder_token(monkeypatch):
    # A leftover .env.example placeholder must NOT be treated as a real cred
    # (consistency with create_jira's _is_real gating).
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_...")
    num, url = autopilot.open_pr(DIAGNOSIS, "AUTO-DEMO")
    assert num == 0
    assert "pull/0" in url


def test_diagnose_and_fix_default_delegates_to_run_fix(monkeypatch):
    monkeypatch.delenv("AUTOFIX_FIX", raising=False)  # default = fix
    import claude_agent
    captured = {}

    def fake_run_fix(incident):
        captured["incident"] = incident
        return FIX_RESULT

    monkeypatch.setattr(claude_agent, "run_fix", fake_run_fix)
    result = autopilot.diagnose_and_fix(SAMPLE_INCIDENT)
    assert captured["incident"] is SAMPLE_INCIDENT
    assert result is FIX_RESULT


def test_diagnose_and_fix_diagnose_only_mode_uses_run_agent(monkeypatch):
    monkeypatch.setenv("AUTOFIX_FIX", "0")  # diagnose-only
    import claude_agent
    monkeypatch.setattr(claude_agent, "run_agent", lambda incident: DIAGNOSIS)
    result = autopilot.diagnose_and_fix(SAMPLE_INCIDENT)
    assert result is DIAGNOSIS


def test_main_runs_end_to_end_in_demo_mode(monkeypatch, capfd):
    monkeypatch.delenv("JIRA_SITE", raising=False)
    monkeypatch.delenv("JIRA_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AUTOFIX_FIX", raising=False)
    monkeypatch.setattr(autopilot, "read_log", lambda: SAMPLE_INCIDENT)
    monkeypatch.setattr(autopilot.time, "sleep", lambda *a, **k: None)
    # Stub the agent so this stays a fast, deterministic wiring test;
    # the live Agent-SDK fix loop is covered by the integration test.
    import claude_agent
    monkeypatch.setattr(claude_agent, "run_fix", lambda incident: FIX_RESULT)
    # Never hit real Slack during tests, even if .env has a live webhook/bot token.
    monkeypatch.setattr(autopilot, "notify_slack", lambda *a, **k: False)
    autopilot.main()
    out = capfd.readouterr().out
    assert "AutoPilot complete" in out
    assert "AUTO-DEMO" in out
    assert "build green" in out  # P5 fix outcome surfaced in the summary


def test_notify_slack_prefers_direct_when_creds_present(monkeypatch):
    import slack_client, slack_agent
    monkeypatch.setattr(slack_client, "has_direct_credentials", lambda: True)
    monkeypatch.setattr(slack_client, "post_text", lambda text: True)
    # bridge must NOT be used when direct is available
    monkeypatch.setattr(slack_agent, "notify_via_agent",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("bridge used despite direct creds")))
    assert autopilot.notify_slack(FIX_RESULT, "AUTO-1", "u", 1, "u") is True


def test_notify_slack_uses_bridge_when_no_direct_and_enabled(monkeypatch):
    import slack_client, slack_agent
    monkeypatch.setattr(slack_client, "has_direct_credentials", lambda: False)
    monkeypatch.setattr(slack_agent, "bridge_enabled", lambda: True)
    called = {}
    monkeypatch.setattr(slack_agent, "notify_via_agent",
                        lambda text, channel: called.setdefault("hit", True) or True)
    assert autopilot.notify_slack(FIX_RESULT, "AUTO-1", "u", 1, "u") is True
    assert called.get("hit")


def test_notify_slack_demo_when_no_direct_and_bridge_off(monkeypatch):
    import slack_client, slack_agent
    monkeypatch.setattr(slack_client, "has_direct_credentials", lambda: False)
    monkeypatch.setattr(slack_agent, "bridge_enabled", lambda: False)
    assert autopilot.notify_slack(FIX_RESULT, "AUTO-1", "u", 1, "u") is False


def test_main_handles_no_incident(monkeypatch, capfd):
    monkeypatch.setattr(autopilot, "read_log", lambda: None)
    monkeypatch.setattr(autopilot.time, "sleep", lambda *a, **k: None)
    autopilot.main()
    out = capfd.readouterr().out
    assert "No application exception" in out
