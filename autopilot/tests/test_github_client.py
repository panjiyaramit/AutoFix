"""Unit tests for Phase 7 GitHub PR flow (git + HTTP mocked)."""
import github_client

DIAG = {
    "root_cause": "null enrollment dereferenced",
    "fix_description": "null-check + 404",
    "files_changed": ["src/.../StudentReportService.java"],
    "test_added": "generateReport_throwsNotFound_whenEnrollmentIsAbsent",
    "test_passed": True,
    "fix_applied": True,
    "confidence": 5,
}


def test_pr_body_includes_jira_root_cause_and_test():
    body = github_client._pr_body(DIAG, "AUTO-9")
    assert "AUTO-9" in body
    assert "null enrollment dereferenced" in body
    assert "generateReport_throwsNotFound_whenEnrollmentIsAbsent" in body
    assert "passed" in body
    assert "does not auto-merge" in body


def test_open_draft_pr_uses_configured_api_base(monkeypatch):
    """GHES support: the PR call must hit GITHUB_API_URL, not hardcoded api.github.com."""
    monkeypatch.setattr(github_client, "GITHUB_API_URL", "https://github.cainc.com/api/v3")
    monkeypatch.setattr(github_client, "GITHUB_OWNER", "hackathon")
    monkeypatch.setattr(github_client, "GITHUB_REPO", "kure-self-healing-pipeline")
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"number": 5, "html_url": "https://github.cainc.com/hackathon/kure-self-healing-pipeline/pull/5"}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        return FakeResp()

    monkeypatch.setattr(github_client.requests, "post", fake_post)
    num, url = github_client.open_draft_pr(DIAG, "AUTO-9", "autopilot/fix-1")
    assert captured["url"] == "https://github.cainc.com/api/v3/repos/hackathon/kure-self-healing-pipeline/pulls"
    assert num == 5


def test_commit_fix_and_open_pr_pushes_then_opens(monkeypatch):
    """The branch must be committed+pushed BEFORE the PR is opened, and the PR
    must target that exact branch (the bug this flow fixes)."""
    calls = []

    def fake_commit_and_push(repo_path, branch_name, commit_message):
        calls.append(("push", branch_name))

    def fake_open_draft_pr(diagnosis, jira_key, branch_name):
        calls.append(("pr", branch_name))
        return 42, "https://github.com/o/r/pull/42"

    monkeypatch.setattr(github_client, "commit_and_push", fake_commit_and_push)
    monkeypatch.setattr(github_client, "open_draft_pr", fake_open_draft_pr)

    num, url = github_client.commit_fix_and_open_pr(DIAG, "KR-9", "/repo")
    assert (num, url) == (42, "https://github.com/o/r/pull/42")
    # push happens first, and both use the SAME branch name
    assert calls[0][0] == "push"
    assert calls[1][0] == "pr"
    assert calls[0][1] == calls[1][1]
    # branch name includes the Jira key
    assert calls[0][1].startswith("KURE-KR-9-")
    # branch name must be bracket-free (git rejects '[' / ']')
    assert "[" not in calls[0][1] and "]" not in calls[0][1]
