"""PostgreSQL's JSON plan, parsed into a small typed tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PlanMode = Literal["analyze", "plain", "skipped", "error"]

# Keys turned into typed fields; everything else stays in `details` for display.
_TYPED = {
    "Node Type", "Relation Name", "Index Name", "Alias", "Join Type", "Startup Cost",
    "Total Cost", "Plan Rows", "Actual Rows", "Actual Loops", "Actual Total Time",
    "Actual Startup Time", "Rows Removed by Filter", "Shared Hit Blocks", "Shared Read Blocks",
    "Temp Written Blocks", "Sort Space Type", "Sort Method", "Hash Batches", "Plans",
}  # fmt: skip


@dataclass
class Flag:
    kind: Literal["seq_scan", "row_estimate", "spill"]
    message: str
    node_type: str
    relation: str | None = None


@dataclass
class PlanNode:
    node_type: str
    relation: str | None
    index: str | None
    alias: str | None
    join_type: str | None
    startup_cost: float
    total_cost: float
    plan_rows: float
    """Rows the planner expected, per loop."""
    actual_rows: float | None
    """Rows produced, per loop (PostgreSQL 18 reports fractions). None without ANALYZE."""
    loops: float | None
    actual_total_ms: float | None
    """Time per loop, including children."""
    rows_removed_by_filter: float | None
    shared_hit_blocks: int | None
    shared_read_blocks: int | None
    temp_written_blocks: int | None
    sort_method: str | None
    sort_space_type: str | None
    hash_batches: int | None
    self_ms: float | None = None
    """Time spent in this node alone, all loops (total minus children)."""
    details: dict[str, Any] = field(default_factory=dict)
    children: list[PlanNode] = field(default_factory=list)


@dataclass
class TriggerRun:
    name: str | None
    relation: str | None
    constraint: str | None
    calls: int | None
    time_ms: float | None


@dataclass
class PlanResult:
    mode: PlanMode
    root: PlanNode | None = None
    planning_ms: float | None = None
    execution_ms: float | None = None
    triggers: list[TriggerRun] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    error: str | None = None
    sqlstate: str | None = None


def _num(node: dict[str, Any], key: str) -> float | None:
    value = node.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _int(node: dict[str, Any], key: str) -> int | None:
    value = node.get(key)
    return int(value) if isinstance(value, (int, float)) else None


def parse_node(node: dict[str, Any]) -> PlanNode:
    children = [parse_node(child) for child in node.get("Plans", [])]
    parsed = PlanNode(
        node_type=str(node.get("Node Type", "?")),
        relation=node.get("Relation Name"),
        index=node.get("Index Name"),
        alias=node.get("Alias"),
        join_type=node.get("Join Type"),
        startup_cost=_num(node, "Startup Cost") or 0.0,
        total_cost=_num(node, "Total Cost") or 0.0,
        plan_rows=_num(node, "Plan Rows") or 0.0,
        actual_rows=_num(node, "Actual Rows"),
        loops=_num(node, "Actual Loops"),
        actual_total_ms=_num(node, "Actual Total Time"),
        rows_removed_by_filter=_num(node, "Rows Removed by Filter"),
        shared_hit_blocks=_int(node, "Shared Hit Blocks"),
        shared_read_blocks=_int(node, "Shared Read Blocks"),
        temp_written_blocks=_int(node, "Temp Written Blocks"),
        sort_method=node.get("Sort Method"),
        sort_space_type=node.get("Sort Space Type"),
        hash_batches=_int(node, "Hash Batches"),
        details={k: v for k, v in node.items() if k not in _TYPED},
        children=children,
    )
    if parsed.actual_total_ms is not None and parsed.loops is not None:
        own = parsed.actual_total_ms * parsed.loops
        for child in children:
            if child.actual_total_ms is not None and child.loops is not None:
                own -= child.actual_total_ms * child.loops
        parsed.self_ms = max(own, 0.0)
    return parsed


def parse_document(doc: dict[str, Any], *, analyzed: bool) -> PlanResult:
    """One element of the array returned by EXPLAIN (FORMAT JSON)."""
    return PlanResult(
        mode="analyze" if analyzed else "plain",
        root=parse_node(doc["Plan"]),
        planning_ms=_num(doc, "Planning Time"),
        execution_ms=_num(doc, "Execution Time"),
        triggers=[
            TriggerRun(
                name=t.get("Trigger Name"),
                relation=t.get("Relation"),
                constraint=t.get("Constraint Name"),
                calls=_int(t, "Calls"),
                time_ms=_num(t, "Time"),
            )
            for t in doc.get("Triggers", [])
        ],
    )


def walk(node: PlanNode) -> list[PlanNode]:
    """The node and all its descendants, parents first."""
    out = [node]
    for child in node.children:
        out.extend(walk(child))
    return out
