"""
AutoPilot — autonomous incident-response orchestrator.
Wires the pipeline end-to-end: read the exception, have the Claude Agent SDK
fix it + add a regression test + run the build (Phase 5), then file a Jira
ticket and open a draft PR. Jira and GitHub fall back to mock results when no
credentials are configured, so the pipeline runs locally for the demo without
creating real tickets/PRs. Set AUTOFIX_FIX=0 for a diagnose-only run (Phase 4,
no code changes).
"""
import os
import time

# Use the OS trust store so requests works behind corporate TLS inspection.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 — optional; falls back to certifi
    pass

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

load_dotenv()  # load autopilot/.env so credential gating sees real values

console = Console()

def read_log():
    from log_reader import read_latest_exception
    incident = read_latest_exception("../backend/logs/app.log")
    return incident.to_dict() if incident else None

def diagnose_and_fix(incident):
    """Phase 5 (default): apply the fix + regression test and run the build.
    Set AUTOFIX_FIX=0 for a Phase-4 diagnose-only run (no code changes)."""
    if os.environ.get("AUTOFIX_FIX", "1") != "0":
        from claude_agent import run_fix
        return run_fix(incident)
    from claude_agent import run_agent
    return run_agent(incident)

_MOCK_JIRA = ("AUTO-DEMO", "https://example.atlassian.net/browse/AUTO-DEMO")

def _is_real(value: str) -> bool:
    """True only if an env value is set AND not a leftover .env.example placeholder."""
    if not value:
        return False
    placeholders = ("yoursite", "you@example.com", "ATATT...", "ghp_...",
                    "your-username", "sk-ant-...")
    return not any(p in value for p in placeholders)

def _jira_configured():
    return _is_real(os.environ.get("JIRA_SITE", "")) and _is_real(os.environ.get("JIRA_TOKEN", ""))

def create_jira(incident):
    """Phase 1 of the two-phase ticket: open a ticket from the incident alone,
    before the fix exists. Enriched later by update_jira()."""
    if not _jira_configured():
        console.print("[dim]  (demo mode: no Jira creds — using mock ticket)[/dim]")
        return _MOCK_JIRA
    from jira_client import create_incident_issue
    try:
        return create_incident_issue(incident)
    except Exception as e:  # noqa: BLE001 — never crash the demo on a Jira error
        console.print(f"[yellow]Jira create failed ({e}); using mock ticket.[/yellow]")
        return _MOCK_JIRA

def update_jira(jira_key, diagnosis, pr_url):
    """Phase 2: enrich the ticket with the full diagnosis + PR link."""
    if jira_key == _MOCK_JIRA[0] or not _jira_configured():
        return
    try:
        from jira_client import update_with_diagnosis
        update_with_diagnosis(jira_key, diagnosis, pr_url)
        console.print(f"[green]✓[/green] Jira ticket [cyan]{jira_key}[/cyan] updated with fix + PR link")
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]Could not update Jira {jira_key}: {e}[/yellow]")

def open_pr(diagnosis, jira_key):
    if not _is_real(os.environ.get("GITHUB_TOKEN", "")):
        console.print("[dim]  (demo mode: no GitHub creds — using mock PR)[/dim]")
        return 0, "https://github.com/example/repo/pull/0"
    from github_client import commit_fix_and_open_pr
    # The git repo holding the agent's fix. Defaults to the repo root (one level
    # up from autopilot/); override with GIT_REPO_DIR for a separate target repo.
    repo_path = os.environ.get("GIT_REPO_DIR", os.path.join(os.path.dirname(__file__), ".."))
    return commit_fix_and_open_pr(diagnosis, jira_key, repo_path)

def _deliver_slack(text, label):
    """Send a pre-built Slack message via the fallback chain:
      1. DIRECT  — bot token / webhook in .env (preferred)
      2. BRIDGE  — Claude Agent SDK posts via an approved Slack MCP
                   (opt-in with AUTOFIX_SLACK_AGENT_BRIDGE=1)
      3. DEMO    — neither: send nothing.
    """
    import slack_client
    if slack_client.has_direct_credentials():
        sent = slack_client.post_text(text)
        if sent:
            console.print(f"[green]✓[/green] Slack {label} (direct).")
        return sent
    import slack_agent
    if slack_agent.bridge_enabled():
        sent = slack_agent.notify_via_agent(text, slack_client.SLACK_CHANNEL)
        if sent:
            console.print(f"[green]✓[/green] Slack {label} (via Claude Agent bridge).")
        else:
            console.print("[yellow]  Slack agent bridge could not deliver (Slack MCP needs a usable token).[/yellow]")
        return sent
    console.print(f"[dim]  (demo mode: no Slack creds — {label} not sent)[/dim]")
    return False

def notify_slack_working(incident, jira_key, jira_url):
    """Early ping: incident detected + ticket filed, fix/PR still in progress."""
    import slack_client
    return _deliver_slack(
        slack_client.build_working_message(incident, jira_key, jira_url),
        "working-on-it notice sent",
    )

def notify_slack(diagnosis, jira_key, jira_url, pr_number, pr_url):
    """Final ping: fix written, tests run, PR opened."""
    import slack_client
    return _deliver_slack(
        slack_client.build_message(diagnosis, jira_key, jira_url, pr_number, pr_url),
        "final summary sent",
    )


def print_summary(jira_key, jira_url, pr_number, pr_url, diagnosis):
    if diagnosis.get("fix_applied"):
        fix_text = "fix + regression test written, " + (
            "build green ✅" if diagnosis.get("test_passed") else "build NOT green ⚠"
        )
    else:
        fix_text = "diagnosis only (no code change)"
    console.print(Panel(
        Text.assemble(
            ("✅ AutoPilot complete\n\n", "bold green"),
            ("Fix:   ", "dim"), (f"{fix_text}\n", "magenta"),
            ("Jira:  ", "dim"), (f"{jira_key}  {jira_url}\n", "cyan"),
            ("PR:    ", "dim"), (f"#{pr_number}  {pr_url}", "cyan"),
        ),
        title="[bold]AutoPilot Summary[/bold]",
        border_style="green",
    ))

def run_pipeline(incident):
    """Run the full incident-response pipeline for an already-detected incident.
    Shared by the one-shot CLI (main) and the live watcher."""
    console.print(f"[green]✓[/green] Exception detected: [bold]{incident['exception_class']}[/bold]")
    time.sleep(1)

    # 2) Create the Jira ticket from the incident (before the fix exists).
    with console.status("[bold]Creating Jira ticket...[/bold]"):
        jira_key, jira_url = create_jira(incident)
    console.print(f"[green]✓[/green] Jira ticket created: [cyan]{jira_key}[/cyan] [dim](diagnosis in progress…)[/dim]")
    time.sleep(1)

    # 2b) Early Slack ping: detected + ticket filed, working on the fix.
    with console.status("[bold]Notifying Slack (working on it)...[/bold]"):
        notify_slack_working(incident, jira_key, jira_url)
    time.sleep(1)

    # 3) Have the agent write the fix + regression test.
    with console.status("[bold]Claude writing fix + regression test...[/bold]"):
        diagnosis = diagnose_and_fix(incident)
    console.print(f"[green]✓[/green] Diagnosis confidence: {diagnosis['confidence']}/5")
    if diagnosis.get("source") == "fallback":
        console.print(
            "[yellow]⚠ Came from the local FALLBACK, not the live Agent SDK. "
            "Install claude-agent-sdk and provide Claude credentials (key/login/gateway) "
            "for a real, code-grounded fix.[/yellow]"
        )
    else:
        console.print("[dim]  source: live Agent SDK[/dim]")
    if diagnosis.get("fix_applied"):
        if diagnosis.get("test_passed"):
            console.print("[green]✓[/green] Fix applied; regression test passes ([bold]./mvnw test[/bold] green).")
        else:
            console.print("[yellow]⚠ Fix applied but the regression test did NOT pass — flag for human review.[/yellow]")
    elif "fix_applied" in diagnosis:
        console.print("[yellow]⚠ No code change written (diagnosis only) — falling through to a PR.[/yellow]")
    time.sleep(1)

    # 4) Open the draft PR with the fix.
    with console.status("[bold]Opening GitHub PR...[/bold]"):
        pr_number, pr_url = open_pr(diagnosis, jira_key)
    console.print(f"[green]✓[/green] Draft PR opened: [cyan]#{pr_number}[/cyan]")
    time.sleep(1)

    # 5) Enrich the Jira ticket with the diagnosis + PR link.
    with console.status("[bold]Updating Jira ticket...[/bold]"):
        update_jira(jira_key, diagnosis, pr_url)
    time.sleep(1)

    # 6) Notify Slack.
    with console.status("[bold]Notifying Slack...[/bold]"):
        notify_slack(diagnosis, jira_key, jira_url, pr_number, pr_url)

    print_summary(jira_key, jira_url, pr_number, pr_url, diagnosis)

def main():
    console.rule("[bold blue]AutoPilot — Incident Response Pipeline[/bold blue]")
    with console.status("[bold]Reading exception from log...[/bold]"):
        incident = read_log()
    if not incident:
        console.print("[yellow]No application exception found in the log — nothing to do.[/yellow]")
        return
    run_pipeline(incident)

if __name__ == "__main__":
    main()
