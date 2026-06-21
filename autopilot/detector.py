"""
detector.py — turns a structured Incident into a live plain-English summary.

When Claude credentials are configured (ANTHROPIC_API_KEY or CLAUDE_BASE_URL),
this streams the summary token-by-token from Claude. When they are not yet
configured, it falls back to a locally-generated summary so the pipeline is
fully runnable today — no code changes needed once the proxy is wired in.
"""
from __future__ import annotations

import sys

from rich.console import Console

from config import config
from log_reader import Incident, read_latest_exception

console = Console()

SYSTEM_PROMPT = (
    "You are an on-call SRE for a K-8 education platform. You receive a single "
    "production exception and explain, in 2-3 concise sentences, what broke and "
    "the most likely root cause. Be specific and plain-spoken. Do not propose a "
    "code fix yet — that happens in a later stage."
)


def _build_user_prompt(incident: Incident) -> str:
    return (
        "A production exception was just detected.\n\n"
        f"Exception : {incident.exception_class}\n"
        f"Message   : {incident.exception_message}\n"
        f"Location  : {incident.file}:{incident.line}\n"
        f"Student   : {incident.student_id}\n"
        f"Year      : {incident.academic_year}\n\n"
        "Traceback (top frames):\n"
        f"{_top_frames(incident.traceback, n=6)}\n\n"
        "Summarize what happened and the most likely root cause."
    )


def _top_frames(traceback: str, n: int) -> str:
    lines = traceback.splitlines()
    # header + exception line + first n stack frames
    keep = []
    frame_count = 0
    for ln in lines:
        if ln.strip().startswith("at "):
            if frame_count >= n:
                continue
            frame_count += 1
        keep.append(ln)
    return "\n".join(keep)


def _fallback_summary(incident: Incident) -> str:
    """Deterministic summary used when no Claude credentials are configured."""
    who = incident.student_id or "a student"
    year = incident.academic_year or "the requested year"
    return (
        f"The report endpoint threw a {incident.exception_class} at "
        f"{incident.file}:{incident.line}. The request for student {who} in "
        f"academic year {year} returned no enrollment record, so the code "
        f"dereferenced a null value. Most likely the enrollment lookup returned "
        f"null and was used without a null check."
    )


def stream_diagnosis(incident: Incident) -> str:
    """
    Stream a plain-English detection summary to the terminal.
    Returns the full summary text.
    """
    console.print("\n[bold cyan]🤖 Analyzing incident...[/bold cyan]")
    console.rule(style="cyan")

    # No credentials yet -> use the local fallback so the demo still runs.
    if not config.anthropic_api_key and not config.claude_base_url:
        text = _fallback_summary(incident)
        console.print(f"[white]{text}[/white]")
        console.rule(style="cyan")
        console.print("[dim](local summary — add Claude credentials to stream live)[/dim]")
        return text

    # Real Claude streaming.
    try:
        client = config.build_anthropic_client()
        collected: list[str] = []
        with client.messages.stream(
            model=config.claude_model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(incident)}],
        ) as stream:
            for chunk in stream.text_stream:
                collected.append(chunk)
                console.print(chunk, end="", style="white")
        console.print()
        console.rule(style="cyan")
        return "".join(collected)
    except Exception as e:  # noqa: BLE001 - surface any SDK/proxy error clearly
        console.print(f"[red]Claude call failed:[/red] {e}")
        console.print("[yellow]Falling back to local summary.[/yellow]")
        text = _fallback_summary(incident)
        console.print(f"[white]{text}[/white]")
        return text


def _main() -> None:
    """Smoke test: python detector.py  (uses the latest exception in the log)"""
    incident = read_latest_exception(config.log_path)
    if incident is None:
        console.print("[yellow]No exception in the log to analyze.[/yellow]")
        sys.exit(0)
    stream_diagnosis(incident)


if __name__ == "__main__":
    _main()
