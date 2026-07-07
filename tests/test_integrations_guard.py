"""Tests for the framework-free @sql_guard decorator."""
import pytest

from verisql.integrations import SQLVerificationError, sql_guard

CLEAN_SQL = "SELECT id, amount FROM orders WHERE status = 'paid' AND order_date >= '2026-01-01'"
FIXABLE_SQL = "SELECT * FROM customers WHERE id NOT IN (1, NULL)"
BROKEN_SQL = "SELECT * FROM"


def test_guard_passes_clean_sql_through():
    @sql_guard()
    def gen() -> str:
        return CLEAN_SQL

    assert gen() == CLEAN_SQL


def test_guard_repairs_fixable_sql():
    @sql_guard()
    def gen() -> str:
        return FIXABLE_SQL

    fixed = gen()
    assert "NULL" not in fixed.upper().replace("IS NOT NULL", "")
    assert "NOT" in fixed.upper()  # intent preserved


def test_guard_raises_on_unfixable_sql():
    @sql_guard()
    def gen() -> str:
        return BROKEN_SQL

    with pytest.raises(SQLVerificationError) as exc_info:
        gen()
    err = exc_info.value
    assert err.diagnosis  # list of flag dicts for feeding back to the generator
    assert err.repair_result.final_sql


def test_guard_binds_question_argument():
    """question_arg wires the NL question into intent checks (date_coverage)."""
    @sql_guard(question_arg="question")
    def gen(question: str) -> str:
        return "SELECT SUM(amount) FROM orders WHERE status = 'paid'"

    # question mentions a time range; SQL has no date filter -> review -> raise
    with pytest.raises(SQLVerificationError):
        gen(question="total revenue last month")


def test_guard_preserves_function_metadata():
    @sql_guard()
    def my_generator() -> str:
        """Docstring survives."""
        return CLEAN_SQL

    assert my_generator.__name__ == "my_generator"
    assert "survives" in (my_generator.__doc__ or "")
