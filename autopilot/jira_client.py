"""Creates and updates Jira issues via the Cloud REST API v3."""
import os
import requests
from dotenv import load_dotenv

# Use the OS trust store so requests works behind corporate TLS inspection.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 — optional; falls back to certifi
    pass

load_dotenv()

JIRA_SITE        = os.environ.get("JIRA_SITE", "").rstrip("/")
JIRA_EMAIL       = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN       = os.environ.get("JIRA_TOKEN", "")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "AUTO")
# Free personal Jira projects often don't have a "Bug" type — make it configurable.
JIRA_ISSUE_TYPE  = os.environ.get("JIRA_ISSUE_TYPE", "Bug")


def _summary(diagnosis: dict) -> str:
    """A concise, incident-specific summary derived from the diagnosis."""
    explicit = diagnosis.get("summary")
    if explicit:
        return explicit[:240]
    root = (diagnosis.get("root_cause") or "").strip()
    if root:
        first = root.split(". ")[0].rstrip(".")
        return f"[AutoFix] {first}"[:240]
    return "[AutoFix] Production incident auto-detected"


def text_to_adf(text: str) -> dict:
    """Wraps plain text in Atlassian Document Format."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": p}],
            }
            for p in paragraphs
        ],
    }


def create_issue(diagnosis: dict) -> tuple[str, str]:
    """Creates a Jira issue from the diagnosis and returns (key, url).

    The description follows the standard AutoFix ticket format (see jira_format):
    Description, Steps to Reproduce, Root Cause, Nature of Fix, Acceptance
    Criteria, and Automation Details.
    """
    from jira_format import build_description

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": _summary(diagnosis),
            "description": build_description(diagnosis),
            "issuetype": {"name": JIRA_ISSUE_TYPE},
            "labels": ["autofix", "auto-pilot", "student-progress"],
        }
    }

    resp = requests.post(
        f"{JIRA_SITE}/rest/api/3/issue",
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    key = data["key"]
    url = f"{JIRA_SITE}/browse/{key}"
    return key, url


def _incident_summary(incident: dict) -> str:
    cls = incident.get("exception_class", "Exception")
    loc = ""
    if incident.get("file"):
        loc = f" in {incident['file']}:{incident.get('line', '?')}"
    return f"[AutoFix] {cls}{loc}"[:240]


def create_incident_issue(incident: dict) -> tuple[str, str]:
    """Phase 1 of the two-phase ticket: open a ticket from the *incident* alone
    (before the fix exists). Returns (key, url). Enriched later via
    update_with_diagnosis()."""
    desc = (
        f"An unhandled {incident.get('exception_class', 'exception')} was detected "
        "in production and picked up by AutoFix.\n\n"
        f"Location: {incident.get('file', 'n/a')}:{incident.get('line', 'n/a')}\n\n"
        f"Request: studentId={incident.get('student_id')}, "
        f"academicYear={incident.get('academic_year')}\n\n"
        "Status: Diagnosis in progress — AutoFix is reading the source, preparing a "
        "fix and a regression test. This ticket will be updated automatically."
    )
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": _incident_summary(incident),
            "description": text_to_adf(desc),
            "issuetype": {"name": JIRA_ISSUE_TYPE},
            "labels": ["autofix", "auto-pilot", "student-progress"],
        }
    }
    resp = requests.post(
        f"{JIRA_SITE}/rest/api/3/issue",
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    key = resp.json()["key"]
    return key, f"{JIRA_SITE}/browse/{key}"


def update_with_diagnosis(key: str, diagnosis: dict, pr_url: str | None = None) -> None:
    """Phase 2: replace the ticket description with the full AutoFix format once the
    fix exists, and append the PR link."""
    from jira_format import build_description

    description = build_description(diagnosis)
    if pr_url:
        description["content"].append({
            "type": "paragraph",
            "content": [{"type": "text", "text": f"PR: {pr_url}"}],
        })
    requests.put(
        f"{JIRA_SITE}/rest/api/3/issue/{key}",
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={"Content-Type": "application/json"},
        json={"fields": {"description": description}},
        timeout=15,
    ).raise_for_status()


def update_description(key: str, pr_url: str) -> None:
    """Appends the PR URL to the Jira ticket description."""
    issue_resp = requests.get(
        f"{JIRA_SITE}/rest/api/3/issue/{key}",
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        timeout=15,
    )
    issue_resp.raise_for_status()
    existing = issue_resp.json()["fields"]["description"]

    # Append PR link paragraph
    existing["content"].append({
        "type": "paragraph",
        "content": [{"type": "text", "text": f"PR: {pr_url}"}],
    })

    requests.put(
        f"{JIRA_SITE}/rest/api/3/issue/{key}",
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={"Content-Type": "application/json"},
        json={"fields": {"description": existing}},
        timeout=15,
    ).raise_for_status()
