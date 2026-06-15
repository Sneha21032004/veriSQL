"""User-extensible repair rules (Bet 2).

The built-in repairs (NOT IN NULL, timestamp equality, != NULL drop) are coded
in Python because they need fine-grained AST mutation. Many other useful repairs
are simpler: "if you see X in the AST, replace it with Y." Those are expressible
as a YAML rule, contributable by anyone, no Python needed.

Rule schema:

    rules:
      - name: utc_now_to_current_timestamp
        description: prefer standard CURRENT_TIMESTAMP over vendor-specific UTC_NOW
        match:
            kind: function
            name: utc_now              # case-insensitive
        replace:
            sql: CURRENT_TIMESTAMP

      - name: trim_leading_zeros_on_pad
        description: LPAD(col, 10, '0') is redundant if col is already numeric
        match:
            kind: function
            name: lpad
        replace:
            keep_first_arg: true        # collapse to LPAD(x, ...) -> x

Only `kind: function` is supported in this first cut — covers the most common
"swap one function for another" repairs. The format intentionally leaves room
to add `kind: column_predicate`, `kind: window`, etc., without breaking files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import expressions as exp

from verisql.repair import Repair


@dataclass
class YamlRule:
    name: str
    description: str
    match: dict[str, Any]
    replace: dict[str, Any]

    def apply(self, ast: exp.Expression, repairs: list[Repair]) -> exp.Expression:
        kind = (self.match or {}).get("kind")
        if kind == "function":
            return self._apply_function(ast, repairs)
        return ast

    def _apply_function(self, ast: exp.Expression, repairs: list[Repair]) -> exp.Expression:
        target = (self.match.get("name") or "").lower()
        if not target:
            return ast
        for fn in list(ast.find_all(exp.Func, exp.Anonymous)):
            # sqlglot.exp.Anonymous holds unknown function names in .this; named
            # builtins expose sql_name(). Cover both.
            if isinstance(fn, exp.Anonymous):
                fn_name = str(fn.this).lower()
            else:
                fn_name = (fn.sql_name() or type(fn).__name__).lower()
            if fn_name != target:
                continue
            before = fn.sql()
            new_node: exp.Expression | None = None
            if self.replace.get("sql"):
                new_node = sqlglot.parse_one(self.replace["sql"])
            elif self.replace.get("keep_first_arg") and fn.args.get("this") is not None:
                new_node = fn.args["this"].copy()
            if new_node is not None:
                fn.replace(new_node)
                repairs.append(Repair(
                    rule=self.name,
                    description=self.description,
                    before_fragment=before,
                    after_fragment=new_node.sql(),
                ))
        return ast


def load_rules(path: str | Path) -> list[YamlRule]:
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [YamlRule(**r) for r in data.get("rules", [])]


def apply_rules(sql: str, rules: list[YamlRule], dialect: str = "duckdb") -> tuple[str, list[Repair]]:
    try:
        ast = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql, []
    repairs: list[Repair] = []
    for rule in rules:
        ast = rule.apply(ast, repairs)
    return (ast.sql(dialect=dialect), repairs) if repairs else (sql, [])
