"""Unit tests for Phase 4 Agent-SDK diagnosis (SDK calls mocked for determinism)."""
import pytest

import claude_agent

SAMPLE = {
    "exception_class": "java.lang.NullPointerException",
    "exception_message": '"enrollment" is null',
    "file": "StudentReportService.java",
    "line": "35",
    "student_id": "4271",
    "academic_year": "2023-24",
    "traceback": "java.lang.NullPointerException ...\n\tat ...:35",
}


def test_build_prompt_includes_incident_and_keeps_json_template():
    p = claude_agent._build_prompt(SAMPLE)
    assert "NullPointerException" in p
    assert "StudentReportService.java:35" in p
    assert "studentId=4271, academicYear=2023-24" in p
    assert '"root_cause"' in p  # {{ }} survived .format with no KeyError


def test_parse_diagnosis_fenced_json():
    text = (
        'reasoning...\n```json\n'
        '{"root_cause":"rc","files_changed":["a"],"fix_description":"fd",'
        '"test_added":"t","confidence":4}\n```\ntrailing'
    )
    d = claude_agent._parse_diagnosis(text)
    assert d["root_cause"] == "rc"
    assert d["files_changed"] == ["a"]
    assert d["confidence"] == 4


def test_parse_diagnosis_bare_object_coerces_confidence():
    d = claude_agent._parse_diagnosis('here {"root_cause":"x","confidence":"5"}')
    assert d["root_cause"] == "x"
    assert d["confidence"] == 5  # "5" -> 5


def test_parse_diagnosis_garbage_returns_none():
    assert claude_agent._parse_diagnosis("no json at all") is None
    assert claude_agent._parse_diagnosis("```json\n{not valid}\n```") is None


def test_run_agent_returns_parsed_diagnosis(monkeypatch):
    async def fake(incident):
        return {"root_cause": "x", "files_changed": [], "fix_description": "y",
                "test_added": "t", "confidence": 5}
    monkeypatch.setattr(claude_agent, "_diagnose_async", fake)
    out = claude_agent.run_agent(SAMPLE)
    assert out["confidence"] == 5
    assert out["root_cause"] == "x"


def test_run_agent_falls_back_when_no_json(monkeypatch):
    async def fake(incident):
        return None
    monkeypatch.setattr(claude_agent, "_diagnose_async", fake)
    out = claude_agent.run_agent(SAMPLE)
    assert out["confidence"] == 2  # deterministic fallback
    assert "StudentReportService.java" in out["files_changed"][0]


def test_run_agent_falls_back_on_sdk_error(monkeypatch):
    async def boom(incident):
        raise RuntimeError("sdk/CLI missing")
    monkeypatch.setattr(claude_agent, "_diagnose_async", boom)
    out = claude_agent.run_agent(SAMPLE)
    assert out["confidence"] == 2  # fallback, no crash


def test_run_agent_tags_live_diagnosis_source(monkeypatch):
    async def fake(incident):
        return {"root_cause": "x", "files_changed": [], "fix_description": "y",
                "test_added": "t", "confidence": 5}
    monkeypatch.setattr(claude_agent, "_diagnose_async", fake)
    out = claude_agent.run_agent(SAMPLE)
    assert out["source"] == "agent-sdk"  # live diagnosis is labelled


def test_run_agent_tags_fallback_source(monkeypatch):
    async def fake(incident):
        return None
    monkeypatch.setattr(claude_agent, "_diagnose_async", fake)
    out = claude_agent.run_agent(SAMPLE)
    assert out["source"] == "fallback"  # degradation is never silent


def test_parse_fix_result_reads_test_passed():
    text = ('```json\n{"root_cause":"rc","files_changed":["a"],"fix_description":"fd",'
            '"test_added":"t","test_passed":true,"confidence":5}\n```')
    d = claude_agent._parse_fix_result(text)
    assert d["test_passed"] is True
    assert d["test_added"] == "t"


def test_parse_fix_result_coerces_stringy_test_passed():
    d = claude_agent._parse_fix_result('{"root_cause":"x","test_passed":"false"}')
    assert d["test_passed"] is False  # "false" string is NOT truthy here


def test_run_fix_marks_applied_and_source(monkeypatch):
    async def fake(incident):
        return {"root_cause": "x", "files_changed": ["F.java"], "fix_description": "y",
                "test_added": "t", "test_passed": True, "confidence": 5}
    monkeypatch.setattr(claude_agent, "_fix_async", fake)
    out = claude_agent.run_fix(SAMPLE)
    assert out["fix_applied"] is True
    assert out["source"] == "agent-sdk"
    assert out["test_passed"] is True


def test_run_fix_falls_back_without_code_change(monkeypatch):
    async def boom(incident):
        raise RuntimeError("sdk missing")
    monkeypatch.setattr(claude_agent, "_fix_async", boom)
    out = claude_agent.run_fix(SAMPLE)
    assert out["fix_applied"] is False     # no code written
    assert out["test_passed"] is False
    assert out["source"] == "fallback"


@pytest.mark.integration
def test_run_agent_live_diagnosis():
    """Live — calls the real Agent SDK over the Claude Code login. Deselected by default.
    Run with:  python -m pytest -m integration -s tests/test_claude_agent.py
    """
    out = claude_agent.run_agent(SAMPLE)
    assert out["confidence"] >= 1
    assert out["root_cause"]
    assert any("StudentReportService" in f for f in out["files_changed"]) \
        or "StudentReportService" in out["root_cause"]


def test_parse_diagnosis_includes_steps_and_criteria():
    text = ('```json\n{"root_cause":"rc","steps_to_reproduce":["s1","s2"],'
            '"files_changed":[],"fix_description":"fd","test_added":"t",'
            '"acceptance_criteria":["a1"],"confidence":4}\n```')
    d = claude_agent._parse_diagnosis(text)
    assert d["steps_to_reproduce"] == ["s1", "s2"]
    assert d["acceptance_criteria"] == ["a1"]


def test_parse_diagnosis_coerces_string_to_list():
    d = claude_agent._parse_diagnosis('{"root_cause":"x","steps_to_reproduce":"only step"}')
    assert d["steps_to_reproduce"] == ["only step"]
    assert d["acceptance_criteria"] == []  # absent → empty list, no crash


def test_fallback_provides_steps_criteria_and_log():
    fb = claude_agent._fallback({
        "student_id": "4271", "academic_year": "2023-24",
        "traceback": "java.lang.NullPointerException\n\tat StudentReportService.java:35",
    })
    assert fb["steps_to_reproduce"] and fb["acceptance_criteria"]
    assert any("4271" in s for s in fb["steps_to_reproduce"])
    assert "NullPointerException" in fb["log_excerpt"]
