from verisql.policy import Policy, InvariantEvaluator


def test_policy_from_dict():
    p = Policy.from_dict({
        "invariants": ["revenue >= 0"],
        "required_filters": {"orders": ["created_at"]},
    })
    assert p.invariants == ["revenue >= 0"]
    assert p.required_filters == {"orders": ["created_at"]}


def test_invariant_eval_true():
    ev = InvariantEvaluator("revenue >= 0")
    assert ev.check({"revenue": 100}) is True
    assert ev.check({"revenue": -5}) is False


def test_invariant_eval_two_columns():
    ev = InvariantEvaluator("active_users <= total_users")
    assert ev.check({"active_users": 3, "total_users": 10}) is True
    assert ev.check({"active_users": 12, "total_users": 10}) is False


def test_invariant_missing_column_returns_none():
    ev = InvariantEvaluator("revenue >= 0")
    assert ev.check({"other": 1}) is None


def test_invariant_null_operand_returns_none():
    ev = InvariantEvaluator("revenue >= 0")
    assert ev.check({"revenue": None}) is None


def test_invariant_compound():
    ev = InvariantEvaluator("a >= 0 AND b <= 1")
    assert ev.check({"a": 5, "b": 1}) is True
    assert ev.check({"a": 5, "b": 2}) is False


def test_invariant_function_node_is_safe():
    """A predicate wrapping a function must not run it — unsupported node yields None."""
    ev = InvariantEvaluator("revenue >= ABS(-5)")
    # ABS is a Func node, unsupported by the walker -> unresolvable -> None (safe default)
    assert ev.check({"revenue": 100}) is None
