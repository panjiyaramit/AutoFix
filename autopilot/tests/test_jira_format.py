"""Unit tests for the structured AutoFix Jira ticket format (ADF)."""
import jira_format

FULL = {
    "root_cause": "NPE at StudentReportService.java:35 dereferenced a null enrollment.",
    "steps_to_reproduce": ["open dashboard", "request 2023-24 for student 4271", "see 500"],
    "files_changed": ["src/.../StudentReportService.java", "src/.../StudentReportServiceTest.java"],
    "fix_description": "null-check + return 404",
    "test_added": "generateReport_returns404_whenNotEnrolled",
    "acceptance_criteria": ["returns 404 not 500", "regression test passes"],
    "log_excerpt": "java.lang.NullPointerException: ...\n\tat StudentReportService.java:35",
    "test_passed": True,
    "fix_applied": True,
    "confidence": 5,
    "source": "agent-sdk",
}

EXPECTED_SECTIONS = [
    "Description", "Steps to Reproduce", "Logs / Stack Trace", "Root Cause",
    "Nature of Fix", "Acceptance Criteria", "Automation Details",
]


def _headings(doc):
    return [n["content"][0]["text"] for n in doc["content"] if n["type"] == "heading"]


def _node_after_heading(doc, title):
    nodes = doc["content"]
    for i, n in enumerate(nodes):
        if n["type"] == "heading" and n["content"][0]["text"] == title:
            return nodes[i + 1]
    return None


def test_build_description_is_valid_adf_doc():
    doc = jira_format.build_description(FULL)
    assert doc["type"] == "doc" and doc["version"] == 1
    assert isinstance(doc["content"], list) and doc["content"]


def test_all_sections_present_and_in_order():
    assert _headings(jira_format.build_description(FULL)) == EXPECTED_SECTIONS


def test_steps_render_as_ordered_list():
    steps = _node_after_heading(jira_format.build_description(FULL), "Steps to Reproduce")
    assert steps["type"] == "orderedList"
    assert len(steps["content"]) == 3


def test_acceptance_criteria_render_as_bullet_list():
    ac = _node_after_heading(jira_format.build_description(FULL), "Acceptance Criteria")
    assert ac["type"] == "bulletList"
    assert len(ac["content"]) == 2


def test_log_section_renders_as_code_block():
    block = _node_after_heading(jira_format.build_description(FULL), "Logs / Stack Trace")
    assert block["type"] == "codeBlock"
    assert "StudentReportService.java:35" in block["content"][0]["text"]


def test_log_section_truncates_long_traces():
    huge = {"log_excerpt": "x" * 9000}
    block = _node_after_heading(jira_format.build_description(huge), "Logs / Stack Trace")
    assert block["type"] == "codeBlock"
    assert "(truncated)" in block["content"][0]["text"]
    assert len(block["content"][0]["text"]) < 4100


def test_log_section_na_when_absent():
    block = _node_after_heading(jira_format.build_description({}), "Logs / Stack Trace")
    assert block["type"] == "paragraph"  # no codeBlock with empty text
    assert block["content"][0]["text"] == "n/a"


def test_missing_fields_degrade_gracefully():
    doc = jira_format.build_description({})  # empty diagnosis still yields a valid ticket
    assert _headings(doc) == EXPECTED_SECTIONS
    steps = _node_after_heading(doc, "Steps to Reproduce")
    # bulletList/orderedList → listItem → paragraph → text
    assert steps["content"][0]["content"][0]["content"][0]["text"] == "n/a"


def test_no_empty_text_nodes(  ):
    """ADF rejects empty text nodes — ensure none are produced, even from {}."""
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                assert node["text"], "empty ADF text node"
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)
    walk(jira_format.build_description({}))
