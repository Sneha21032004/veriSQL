"""LangChain adapter — VeriSQL's oracle as LangChain tools.

    pip install verisql[langchain]

    from verisql.integrations.langchain import make_verisql_tools
    tools = make_verisql_tools(connector=db)
    agent = create_react_agent(llm, tools)   # any LangChain agent constructor
"""
from __future__ import annotations

from typing import Any

from verisql.integrations._core import fix_payload, verify_payload


def make_verisql_tools(
    connector: Any = None,
    dialect: str = "duckdb",
    policy: Any = None,
) -> list:
    """Build [verify_sql, fix_sql] LangChain tools bound to your database.

    Raises ImportError with an install hint when langchain-core is missing.
    """
    try:
        from langchain_core.tools import tool
    except ImportError as e:
        raise ImportError(
            "langchain-core is required for this adapter: pip install verisql[langchain]"
        ) from e

    @tool
    def verify_sql(sql: str, question: str = "") -> dict:
        """Deterministically verify an SQL query for silent failures (NULL
        semantics, cartesian joins, missing date scope, schema errors).
        Returns verdict, confidence, and a diagnosis per problem."""
        return verify_payload(sql, question=question, dialect=dialect,
                              connector=connector, policy=policy)

    @tool
    def fix_sql(sql: str, question: str = "") -> dict:
        """Verify an SQL query AND auto-repair deterministic bugs, then
        re-verify. Returns corrected SQL ready to execute. Prefer this
        before running any query."""
        return fix_payload(sql, question=question, dialect=dialect,
                           connector=connector, policy=policy)

    return [verify_sql, fix_sql]
