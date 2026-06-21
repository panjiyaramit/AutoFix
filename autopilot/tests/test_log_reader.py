"""Unit tests for the log parser (Phase 2 core logic — previously untested)."""
import pytest

from log_reader import read_latest_exception

NPE_LOG = (
    "2026-06-02 09:15:42 INFO  c.e.s.c.StudentReportController - Generating report for studentId=4271, academicYear=2024-25\n"
    "2026-06-02 09:16:05 ERROR c.e.s.e.GlobalExceptionHandler - Unhandled exception. Request params: studentId=4271, academicYear=2023-24\n"
    'java.lang.NullPointerException: Cannot invoke "com.example.studentprogress.model.Enrollment.getGradeLevel()" because "enrollment" is null\n'
    "\tat com.example.studentprogress.service.StudentReportService.generateReport(StudentReportService.java:35)\n"
    "\tat com.example.studentprogress.controller.StudentReportController.getReport(StudentReportController.java:42)\n"
)


def _write(tmp_path, text):
    p = tmp_path / "app.log"
    p.write_text(text)
    return p


def test_parses_seeded_npe(tmp_path):
    incident = read_latest_exception(_write(tmp_path, NPE_LOG))
    assert incident is not None
    assert incident.exception_class == "java.lang.NullPointerException"
    assert incident.file == "StudentReportService.java"
    assert incident.line == "35"
    assert incident.student_id == "4271"
    assert incident.academic_year == "2023-24"


def test_info_only_log_has_no_incident(tmp_path):
    log = "2026-06-02 09:15:42 INFO  c.e.s.c.StudentReportController - all good\n"
    assert read_latest_exception(_write(tmp_path, log)) is None


def test_returns_most_recent_exception(tmp_path):
    second = (
        "2026-06-02 10:00:00 ERROR c.e.s.e.GlobalExceptionHandler - Unhandled exception. Request params: studentId=4272, academicYear=2021-22\n"
        "java.lang.IllegalStateException: boom\n"
        "\tat com.example.studentprogress.service.StudentReportService.generateReport(StudentReportService.java:51)\n"
    )
    incident = read_latest_exception(_write(tmp_path, NPE_LOG + second))
    assert incident.exception_class == "java.lang.IllegalStateException"
    assert incident.line == "51"
    assert incident.student_id == "4272"


def test_to_dict_has_expected_keys(tmp_path):
    incident = read_latest_exception(_write(tmp_path, NPE_LOG))
    d = incident.to_dict()
    for key in ("exception_class", "exception_message", "file", "line",
                "student_id", "academic_year", "traceback"):
        assert key in d


def test_missing_log_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_latest_exception(tmp_path / "does-not-exist.log")
