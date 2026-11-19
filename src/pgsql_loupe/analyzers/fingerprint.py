"""Turn SQL into a fingerprint: the statement's shape with every value replaced by `?`.

    SELECT * FROM t WHERE id = 5            -> select * from t where id = ?
    select * from t where id = %s           -> select * from t where id = ?
    SELECT * FROM t WHERE id IN (1, 2, 3)   -> select * from t where id in (...)

Statements with the same fingerprint differ only in their values, which is what an N+1
pattern looks like. This is a tokenizer for PostgreSQL's lexical rules, not a parser; see
docs/adr/0004-sql-fingerprint.md.
"""

from __future__ import annotations

import re

_SPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_WORD = re.compile(r"[A-Za-z_\u0080-￿][A-Za-z0-9_$\u0080-￿]*")
_PSYCOPG_PLACEHOLDER = re.compile(r"%(?:\([^)]*\))?[sbt]")
_POSITIONAL = re.compile(r"\$\d+")
_DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_STRING_PREFIX = re.compile(r"(?:[eEbBxXnN]|[uU]&)'")
_OPERATOR = re.compile(r"::|->>|->|#>>|#>|<=|>=|<>|!=|\|\||[^\sA-Za-z0-9_]")

VALUE = "?"
LIST = "(...)"
LITERAL_WORDS = frozenset({"true", "false"})
# After these tokens a '-' is a sign, not a subtraction: `= -1`, `(-1`, `, -1`.
_SIGN_CONTEXT = frozenset(
    {"=", "<", ">", "<=", ">=", "<>", "!=", "(", ",", "[", "+", "-", "*", "/"}
)


def _skip_string(sql: str, start: int, backslash_escapes: bool) -> int:
    """Index just after the closing quote of a '...' literal starting at `start`."""
    i = start + 1
    while i < len(sql):
        char = sql[i]
        if backslash_escapes and char == "\\":
            i += 2
            continue
        if char == "'":
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return len(sql)


def _skip_block_comment(sql: str, start: int) -> int:
    depth, i = 0, start
    while i < len(sql):
        if sql.startswith("/*", i):
            depth, i = depth + 1, i + 2
        elif sql.startswith("*/", i):
            depth, i = depth - 1, i + 2
            if depth == 0:
                return i
        else:
            i += 1
    return len(sql)


def tokenize(sql: str) -> list[str]:
    """Split SQL into lower-cased tokens, with every literal and placeholder as VALUE."""
    tokens: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        char = sql[i]
        if char.isspace():
            i = _SPACE.match(sql, i).end()  # type: ignore[union-attr]
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
        elif sql.startswith("/*", i):
            i = _skip_block_comment(sql, i)
        elif char == "'":
            i = _skip_string(sql, i, backslash_escapes=False)
            tokens.append(VALUE)
        elif (m := _STRING_PREFIX.match(sql, i)) and not (
            tokens and _is_word(tokens[-1]) and _glued(sql, i)
        ):
            i = _skip_string(sql, m.end() - 1, backslash_escapes=m.group(0)[0] in "eE")
            tokens.append(VALUE)
        elif char == '"':
            end = i + 1
            while end < n:
                if sql[end] == '"':
                    if end + 1 < n and sql[end + 1] == '"':
                        end += 2
                        continue
                    break
                end += 1
            tokens.append(sql[i : end + 1])  # quoted identifiers keep their case
            i = end + 1
        elif char == "$" and (m := _POSITIONAL.match(sql, i)):
            tokens.append(VALUE)
            i = m.end()
        elif char == "$" and (m := _DOLLAR_TAG.match(sql, i)):
            close = sql.find(m.group(0), m.end())
            i = n if close == -1 else close + len(m.group(0))
            tokens.append(VALUE)
        elif char == "%" and (m := _PSYCOPG_PLACEHOLDER.match(sql, i)):
            tokens.append(VALUE)
            i = m.end()
        elif sql.startswith("%%", i):
            tokens.append("%")  # psycopg's escaped percent sign
            i += 2
        elif m := _WORD.match(sql, i):
            word = m.group(0).lower()
            tokens.append(VALUE if word in LITERAL_WORDS else word)
            i = m.end()
        elif m := _NUMBER.match(sql, i):
            if tokens and tokens[-1] == "-" and (len(tokens) == 1 or tokens[-2] in _SIGN_CONTEXT):
                tokens.pop()  # `= -1` is the value -1, not a subtraction
            tokens.append(VALUE)
            i = m.end()
        else:
            m = _OPERATOR.match(sql, i)
            assert m is not None
            tokens.append(m.group(0))
            i = m.end()
    while tokens and tokens[-1] == ";":
        tokens.pop()
    return tokens


def _is_word(token: str) -> bool:
    return bool(_WORD.fullmatch(token))


def _glued(sql: str, i: int) -> bool:
    """True if position i directly follows an identifier character (e.g. `name'` is not E'')."""
    return i > 0 and (sql[i - 1].isalnum() or sql[i - 1] == "_")


def _collapse_lists(tokens: list[str]) -> list[str]:
    """`( ? , ? , ? )` -> `(...)`, `[ ? , ? ]` -> `[...]`, and `(...), (...)` -> `(...)`."""
    out: list[str] = []
    for token in tokens:
        out.append(token)
        for opener, closer, folded in (("(", ")", LIST), ("[", "]", "[...]")):
            if token != closer or opener not in out:
                continue
            start = len(out) - 1 - out[::-1].index(opener)
            inner = out[start + 1 : -1]
            if inner and all(t in {VALUE, ","} for t in inner) and VALUE in inner:
                del out[start:]
                out.append(folded)
        while len(out) >= 3 and out[-1] == LIST and out[-2] == "," and out[-3] == LIST:
            del out[-2:]  # VALUES (...), (...), (...) -> VALUES (...)
    return out


_NO_SPACE_BEFORE = frozenset({")", ",", ".", "::", "]", "[", "[...]"})
_NO_SPACE_AFTER = frozenset({"(", ".", "::", "["})


def _join(tokens: list[str]) -> str:
    parts: list[str] = []
    for index, token in enumerate(tokens):
        if index and token not in _NO_SPACE_BEFORE and tokens[index - 1] not in _NO_SPACE_AFTER:
            parts.append(" ")
        parts.append(token)
    return "".join(parts)


def fingerprint(sql: str) -> str:
    """The statement's shape: lower case, no comments, values as `?`, lists as `(...)`."""
    return _join(_collapse_lists(tokenize(sql)))
