"""
log_watcher.py — real-time tailer for the Spring Boot log file.

Watches backend/logs/app.log like `tail -f`, assembles complete log blocks
(a header line plus its traceback continuation lines), and fires a callback
the moment a new application exception is detected.

Two modes:
    python log_watcher.py            # one-shot: report the latest exception, exit
    python log_watcher.py --watch    # continuous: wait for new exceptions live
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel

from config import config
from detector import stream_diagnosis
from log_reader import (
    Incident,
    is_log_header,
    parse_exception_block,
    read_latest_exception,
)

console = Console()

# How long (seconds) with no new lines before we flush a trailing block.
FLUSH_IDLE_SECONDS = 0.5
# Poll interval when sitting at the end of the file.
POLL_SECONDS = 0.2


IncidentCallback = Callable[[Incident], None]


class LogWatcher:
    def __init__(self, log_path: Path, on_incident: IncidentCallback):
        self.log_path = Path(log_path)
        self.on_incident = on_incident
        self._current_block: list[str] = []
        self._last_key: tuple | None = None

    # -- block assembly ---------------------------------------------------

    def _dedupe_key(self, incident: Incident) -> tuple:
        return (incident.timestamp, incident.exception_class, incident.line)

    def _flush_block(self) -> None:
        """Parse the buffered block; fire callback if it's a new incident."""
        if not self._current_block:
            return
        block, self._current_block = self._current_block, []
        incident = parse_exception_block(block)
        if incident is None:
            return
        key = self._dedupe_key(incident)
        if key == self._last_key:
            return  # same exception we just reported; skip
        self._last_key = key
        self.on_incident(incident)

    def _handle_line(self, line: str) -> None:
        if is_log_header(line):
            # A new entry begins -> the previous block is complete.
            self._flush_block()
            self._current_block = [line]
        elif self._current_block:
            # Continuation (traceback) line.
            self._current_block.append(line)

    # -- watch loop -------------------------------------------------------

    def watch(self) -> None:
        """Tail the file forever, processing new lines as they arrive."""
        if not self.log_path.exists():
            console.print(
                f"[red]Log file not found:[/red] {self.log_path}\n"
                f"Start the backend first: [cyan]cd backend && mvn spring-boot:run[/cyan]"
            )
            sys.exit(1)

        console.print(
            Panel(
                f"Watching [cyan]{self.log_path}[/cyan]\n"
                f"Trigger the bug in the dashboard to see detection live.\n"
                f"[dim]Press Ctrl-C to stop.[/dim]",
                title="[bold]AutoFix — Log Watcher[/bold]",
                border_style="blue",
            )
        )

        with self.log_path.open("r", errors="replace") as f:
            f.seek(0, 2)  # jump to end: ignore pre-existing history
            buf = ""
            last_activity = time.monotonic()

            while True:
                chunk = f.readline()
                if chunk:
                    buf += chunk
                    if buf.endswith("\n"):
                        self._handle_line(buf.rstrip("\n"))
                        buf = ""
                        last_activity = time.monotonic()
                else:
                    # At EOF for now. Flush a trailing block if we've gone idle.
                    if (
                        self._current_block
                        and (time.monotonic() - last_activity) > FLUSH_IDLE_SECONDS
                    ):
                        self._flush_block()
                    time.sleep(POLL_SECONDS)


def default_on_incident(incident: Incident) -> None:
    """Default handler: print a concise detection summary."""
    console.print()
    console.print(
        Panel(
            f"[bold red]{incident.exception_class}[/bold red]\n"
            f"[white]{incident.exception_message or ''}[/white]\n\n"
            f"[dim]Location:[/dim] {incident.file}:{incident.line}\n"
            f"[dim]Student:[/dim]  {incident.student_id}\n"
            f"[dim]Year:[/dim]     {incident.academic_year}\n"
            f"[dim]Time:[/dim]     {incident.timestamp}",
            title="[bold]🔴 Exception Detected[/bold]",
            border_style="red",
        )
    )
    # Hand the incident to the detector for a live plain-English summary.
    stream_diagnosis(incident)


def _print_detection(incident: Incident) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold red]{incident.exception_class}[/bold red]\n"
            f"[white]{incident.exception_message or ''}[/white]\n\n"
            f"[dim]Location:[/dim] {incident.file}:{incident.line}\n"
            f"[dim]Student:[/dim]  {incident.student_id}\n"
            f"[dim]Year:[/dim]     {incident.academic_year}\n"
            f"[dim]Time:[/dim]     {incident.timestamp}",
            title="[bold]🔴 Exception Detected[/bold]",
            border_style="red",
        )
    )


def pipeline_on_incident(incident: Incident) -> None:
    """Detection handler that runs the FULL pipeline: diagnose → fix → Jira → PR → Slack."""
    _print_detection(incident)
    import autopilot
    autopilot.run_pipeline(incident.to_dict())
    console.print("\n[dim]…back to watching for the next exception.[/dim]\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoFix log watcher")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch for new exceptions (default: one-shot)",
    )
    parser.add_argument(
        "--pipeline",
        action="store_true",
        help="On each detected exception, run the full pipeline (diagnose→fix→Jira→PR→Slack) "
             "instead of just printing a diagnosis summary.",
    )
    args = parser.parse_args()

    handler = pipeline_on_incident if args.pipeline else default_on_incident

    if args.watch:
        watcher = LogWatcher(config.log_path, on_incident=handler)
        try:
            watcher.watch()
        except KeyboardInterrupt:
            console.print("\n[dim]Watcher stopped.[/dim]")
    else:
        # One-shot mode.
        incident = read_latest_exception(config.log_path)
        if incident is None:
            console.print("[yellow]No application exception found in the log.[/yellow]")
            return
        handler(incident)


if __name__ == "__main__":
    main()
