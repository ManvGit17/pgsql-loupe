"""Decide how a statement may be explained. See docs/adr/0003-plan-capture-safety.md.

The rules only ever err towards safety: a write keyword appearing anywhere (even inside a
string literal) turns a read into a write, which loses ANALYZE but can never cause a write
to be executed.
"""

from __future__ import annotations

import re
from typing import Literal

StatementClass = Literal["read", "write", "none"]

_LEADING_COMMENTS = re.compile(r"\A(?:\s+|--[^\n]*(?:\n|\Z)|/\*.*?\*/)*", re.DOTALL)
_FIRST_WORD = re.compile(r"[A-Za-z]+")
_WRITE_WORDS = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE)\b", re.IGNORECASE)
_LOCKING = re.compile(r"\bFOR\s+(NO\s+KEY\s+UPDATE|UPDATE|KEY\s+SHARE|SHARE)\b", re.IGNORECASE)
_SELECT_INTO = re.compile(r"\bINTO\b", re.IGNORECASE)

READS = frozenset({"SELECT", "VALUES", "TABLE", "WITH"})
WRITES = frozenset({"INSERT", "UPDATE", "DELETE", "MERGE"})


def first_keyword(sql: str) -> str:
    rest = _LEADING_COMMENTS.sub("", sql, count=1)
    match = _FIRST_WORD.match(rest)
    return match.group(0).upper() if match else ""


def classify(sql: str) -> StatementClass:
    """'read' may be analysed in a read-only transaction; 'write' is explained without
    running it unless analyze_writes is on; 'none' is never explained."""
    keyword = first_keyword(sql)
    if keyword in WRITES:
        return "write"
    if keyword not in READS:
        return "none"
    if _LOCKING.search(sql) or _WRITE_WORDS.search(sql):
        return "write"  # row locks, or a data-modifying WITH
    if keyword == "SELECT" and _SELECT_INTO.search(sql):
        return "write"  # SELECT ... INTO creates a table
    return "read"
