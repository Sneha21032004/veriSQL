"""Tests for LangChain / LlamaIndex adapters.

Behavior tests run only when the framework is installed; the soft-import
error message is always tested.
"""
import pytest

FIXABLE_SQL = "SELECT * FROM customers WHERE id NOT IN (1, NULL)"


def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def test_langchain_factory_soft_import():
    from verisql.integrations.langchain import make_verisql_tools

    if not _has("langchain_core"):
        with pytest.raises(ImportError, match="pip install"):
            make_verisql_tools()
        return

    tools = make_verisql_tools()
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"verify_sql", "fix_sql"}
    fix_tool = next(t for t in tools if t.name == "fix_sql")
    result = fix_tool.invoke({"sql": FIXABLE_SQL})
    assert result["verdict"] == "verified"


def test_llamaindex_factory_soft_import():
    from verisql.integrations.llamaindex import make_verisql_tools

    if not _has("llama_index.core"):
        with pytest.raises(ImportError, match="pip install"):
            make_verisql_tools()
        return

    tools = make_verisql_tools()
    assert len(tools) == 2
    names = {t.metadata.name for t in tools}
    assert names == {"verify_sql", "fix_sql"}
    fix_tool = next(t for t in tools if t.metadata.name == "fix_sql")
    result = fix_tool.call(sql=FIXABLE_SQL)
    assert result.raw_output["verdict"] == "verified"
