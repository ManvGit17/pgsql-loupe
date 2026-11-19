"""Core pieces that need no database."""

from __future__ import annotations

import pytest

import pgsql_loupe
from pgsql_loupe.core.callsite import find_call_site
from pgsql_loupe.core.redact import redact_params, show


def test_package_imports() -> None:
    assert pgsql_loupe.__version__


def test_trace_is_inactive_outside_the_block() -> None:
    with pgsql_loupe.trace("x") as t:
        assert pgsql_loupe.current_trace() is t
    assert pgsql_loupe.current_trace() is None


def test_a_trace_block_cannot_be_entered_twice() -> None:
    block = pgsql_loupe.trace()
    with block, pytest.raises(RuntimeError), block:
        pass


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (None, None),
        ((1, "a"), ["1", "'a'"]),
        (
            {"user": "bob", "Password": "x", "auth_token": "y"},
            {"user": "'bob'", "Password": "<redacted>", "auth_token": "<redacted>"},
        ),
        (b"\x00" * 50, ["<50 bytes>"]),
        (5, ["5"]),
    ],
)
def test_redact_params(params: object, expected: object) -> None:
    assert redact_params(params) == expected


def test_show_truncates() -> None:
    assert show("y" * 500).endswith("... (502 chars)")


def test_call_site_is_this_file() -> None:
    site = find_call_site()
    assert site is not None
    assert (site.file, site.function) == (__file__, "test_call_site_is_this_file")
