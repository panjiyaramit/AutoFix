"""
log_reader.py — parses Spring Boot log lines into structured incident data.

The backend logs with this pattern (see application.properties):
    %d{yyyy-MM-dd HH:mm:ss} %-5level %logger{36} - %msg%n

So a log entry looks like:
    2026-06-02 13:18:06 ERROR c.e.s.e.GlobalExceptionHandler - Unhandled exception. Request params: studentId=4271, academicYear=2023-24
    java.lang.NullPointerException: Cannot invoke "...getGradeLevel()" because "enrollment" is null
        at com.example.studentprogress.service.StudentReportService.generateReport(StudentReportService.java:35)
        ...

This module turns one such ERROR "block" (header line + traceback lines)
into a structured Incident dict, or returns None if the block is not a
real application exception we care about.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

# A log line that starts a new entry: "2026-06-02 13:18:06 LEVEL logger - msg"
HEADER_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>\w+)\s+"
    r"(?P<logger>\S+)\s+-\s+"
    r"(?P<msg>.*)$"
)

# Request-param extraction from the GlobalExceptionHandler message.
STUDENT_RE = re.compile(r"studentId=([^,\s]+)")
YEAR_RE = re.compile(r"academicYear=([^,\s]+)")

# The exception line right after the header, e.g.
#   java.lang.NullPointerException: Cannot invoke "..."
EXCEPTION_RE = re.compile(
    r"^(?P<cls>(?:[\w$]+\.)+[\w$]*(?:Exception|Error))(?::\s*(?P<emsg>.*))?$"
)

# An application stack frame inside our own package:
#   at com.example.studentprogress.service.StudentReportService.generateReport(StudentReportService.java:35)
APP_FRAME_RE = re.compile(
    r"at\s+com\.example\.studentprogress\.[\w.$]+\((?P<file>[\w$]+\.java):(?P<line>\d+)\)"
)


@dataclass
class Incident:
    timestamp: str
    logger: str
    header_message: str
    student_id: str | None
    academic_year: str | None
    exception_class: str | None
    exception_message: str | None
    file: str | None
    line: str | None
    traceback: str

    def to_dict(self) -> dict:
        return asdict(self)


def is_log_header(line: str) -> bool:
    """True if the line starts a new log entry (begins with a timestamp)."""
    return HEADER_RE.match(line) is not None


def is_error_header(line: str) -> bool:
    """True if the line is the start of an ERROR-level entry."""
    m = HEADER_RE.match(line)
    return bool(m) and m.group("level") == "ERROR"


def parse_exception_block(block_lines: list[str]) -> Incident | None:
    """
    Parse a single block (one header line + its continuation/traceback lines)
    into an Incident. Returns None if the block is not an ERROR with an
    application exception we recognize.
    """
    if not block_lines:
        return None

    header = HEADER_RE.match(block_lines[0])
    if not header or header.group("level") != "ERROR":
        return None

    msg = header.group("msg")

    # Ignore noise we deliberately don't treat as incidents.
    if "favicon" in msg.lower() or "NoResourceFoundException" in "\n".join(block_lines):
        return None

    student = STUDENT_RE.search(msg)
    year = YEAR_RE.search(msg)

    # The traceback is everything after the header line.
    traceback_lines = block_lines[1:]
    traceback_text = "\n".join(block_lines).strip()

    # First non-empty traceback line should be the exception class + message.
    exception_class = None
    exception_message = None
    for ln in traceback_lines:
        stripped = ln.strip()
        if not stripped:
            continue
        ex = EXCEPTION_RE.match(stripped)
        if ex:
            exception_class = ex.group("cls")
            exception_message = (ex.group("emsg") or "").strip() or None
        break

    # Find the first stack frame inside our own application package.
    file_name = None
    line_no = None
    for ln in traceback_lines:
        frame = APP_FRAME_RE.search(ln)
        if frame:
            file_name = frame.group("file")
            line_no = frame.group("line")
            break

    return Incident(
        timestamp=header.group("ts"),
        logger=header.group("logger"),
        header_message=msg,
        student_id=student.group(1) if student else None,
        academic_year=year.group(1) if year else None,
        exception_class=exception_class,
        exception_message=exception_message,
        file=file_name,
        line=line_no,
        traceback=traceback_text,
    )


def split_into_blocks(lines: list[str]) -> list[list[str]]:
    """
    Group raw log lines into blocks. A new block starts at every line that
    is a log header; continuation lines (traceback) attach to the current block.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if is_log_header(line):
            if current:
                blocks.append(current)
            current = [line.rstrip("\n")]
        elif current:
            current.append(line.rstrip("\n"))
    if current:
        blocks.append(current)
    return blocks


def read_latest_exception(log_path: str | Path) -> Incident | None:
    """
    One-shot mode: scan the whole log file and return the most recent
    application exception, or None if there isn't one.
    """
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    lines = path.read_text(errors="replace").splitlines()
    blocks = split_into_blocks(lines)

    latest: Incident | None = None
    for block in blocks:
        incident = parse_exception_block(block)
        if incident:
            latest = incident  # keep overwriting -> ends on the last one
    return latest


def _main() -> None:
    """Smoke test: python log_reader.py"""
    import json
    from config import config

    print("Parsing latest exception from:", config.log_path)
    print("-" * 60)
    incident = read_latest_exception(config.log_path)
    if incident is None:
        print("No application exception found in the log.")
        return
    print(json.dumps(incident.to_dict(), indent=2))


if __name__ == "__main__":
    _main()
