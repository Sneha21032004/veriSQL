"""Tests for OpenAI-compatible function-calling specs and dispatch."""
import json

import pytest

from verisql.integrations.openai_tools import OPENAI_TOOL_SPECS, dispatch_tool_call

FIXABLE_SQL = "SELECT * FROM customers WHERE id NOT IN (1, NULL)"


def test_tool_specs_shape():
    assert isinstance(OPENAI_TOOL_SPECS, list)
    names = {spec["function"]["name"] for spec in OPENAI_TOOL_SPECS}
    assert names == {"verify_sql", "fix_sql"}
    for spec in OPENAI_TOOL_SPECS:
        assert spec["type"] == "function"
        params = spec["function"]["parameters"]
        assert params["type"] == "object"
        assert "sql" in params["properties"]
        assert "sql" in params["required"]


def test_specs_are_json_serializable():
    json.dumps(OPENAI_TOOL_SPECS)  # must not raise


def test_dispatch_verify_flags_null_bug():
    result = dispatch_tool_call("verify_sql", {"sql": FIXABLE_SQL})
    assert result["verdict"] in ("needs_correction", "rejected")
    assert any("null" in d["message"].lower() or "null" in d["check"]
               for d in result["diagnosis"])


def test_dispatch_fix_repairs_null_bug():
    result = dispatch_tool_call("fix_sql", {"sql": FIXABLE_SQL})
    assert result["verdict"] == "verified"
    assert "NULL" not in result["final_sql"].upper()
    assert result["repairs_applied"]


def test_dispatch_accepts_json_string_arguments():
    """OpenAI returns tool arguments as a JSON string — accept that directly."""
    result = dispatch_tool_call("fix_sql", json.dumps({"sql": FIXABLE_SQL}))
    assert result["verdict"] == "verified"


def test_dispatch_unknown_tool_raises():
    with pytest.raises(ValueError, match="unknown tool"):
        dispatch_tool_call("drop_database", {"sql": "SELECT 1"})
