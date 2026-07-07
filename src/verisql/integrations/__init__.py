"""Drop VeriSQL's oracle into any agent framework.

- `sql_guard` / `SQLVerificationError` — framework-free decorator, zero deps
- `verisql.integrations.openai_tools` — OpenAI-compatible function calling, zero deps
- `verisql.integrations.langchain` — LangChain tools (`pip install verisql[langchain]`)
- `verisql.integrations.llamaindex` — LlamaIndex tools (`pip install verisql[llamaindex]`)
"""
from verisql.integrations.guard import SQLVerificationError, sql_guard

__all__ = ["SQLVerificationError", "sql_guard"]
