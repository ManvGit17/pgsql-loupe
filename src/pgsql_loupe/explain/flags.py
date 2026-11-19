"""Warnings read off a plan: big sequential scans, bad row estimates, spills to disk."""

from __future__ import annotations

from dataclasses import dataclass

from pgsql_loupe.explain.plan import Flag, PlanNode, PlanResult, walk


@dataclass(frozen=True)
class FlagThresholds:
    seq_scan_rows: int = 10_000
    """A sequential scan reading at least this many rows is flagged."""
    estimate_factor: float = 10.0
    """Expected vs actual rows differing by this factor or more is flagged..."""
    estimate_min_rows: float = 100.0
    """...if the larger of the two is at least this many rows (avoids noise on tiny nodes)."""


def _scanned_rows(node: PlanNode) -> float:
    if node.actual_rows is None:  # plain EXPLAIN: only the estimate is known
        return node.plan_rows
    loops = node.loops or 1.0
    return (node.actual_rows + (node.rows_removed_by_filter or 0.0)) * loops


def node_flags(node: PlanNode, limits: FlagThresholds) -> list[Flag]:
    flags: list[Flag] = []
    if node.node_type == "Seq Scan":
        scanned = _scanned_rows(node)
        if scanned >= limits.seq_scan_rows:
            word = "reads" if node.actual_rows is not None else "is expected to read"
            flags.append(
                Flag(
                    "seq_scan",
                    f"Sequential scan on {node.relation} {word} {scanned:,.0f} rows",
                    node.node_type,
                    node.relation,
                )
            )
    if node.actual_rows is not None:
        expected, actual = node.plan_rows, node.actual_rows
        high, low = max(expected, actual), max(min(expected, actual), 1.0)
        if high >= limits.estimate_min_rows and high / low >= limits.estimate_factor:
            flags.append(
                Flag(
                    "row_estimate",
                    f"{node.node_type} expected {expected:,.0f} rows per loop, got {actual:,.0f}",
                    node.node_type,
                    node.relation,
                )
            )
    if node.sort_space_type == "Disk":
        flags.append(
            Flag(
                "spill", f"Sort spilled to disk ({node.sort_method})", node.node_type, node.relation
            )
        )
    if (node.hash_batches or 1) > 1:
        flags.append(
            Flag(
                "spill",
                f"Hash used {node.hash_batches} batches (spilled to disk)",
                node.node_type,
                node.relation,
            )
        )
    return flags


def add_flags(result: PlanResult, limits: FlagThresholds) -> PlanResult:
    if result.root is not None:
        result.flags = [flag for node in walk(result.root) for flag in node_flags(node, limits)]
    return result
