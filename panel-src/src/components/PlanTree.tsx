import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { ms } from "../lib/format";
import { explainNode, nodeTone } from "../lib/planNodes";
import type { PlanNode, PlanResult } from "../types";

const DETAIL_KEYS = [
  "Filter",
  "Index Cond",
  "Hash Cond",
  "Join Filter",
  "Merge Cond",
  "Sort Key",
  "Recheck Cond",
  "Group Key",
];

const TONE = { good: "text-good", warn: "text-warn", plain: "text-ink" } as const;

function describe(node: PlanNode): string {
  const parts: string[] = [];
  if (node.index) parts.push(`using ${node.index}`);
  if (node.relation) parts.push(`on ${node.relation}`);
  if (node.join_type && node.node_type.includes("Join")) parts.push(`(${node.join_type})`);
  return parts.join(" ");
}

function rows(node: PlanNode): string {
  const expected = Math.round(node.plan_rows);
  if (node.actual_rows == null) return `~${expected} rows`;
  const actual = Math.round(node.actual_rows * (node.loops ?? 1));
  return `${actual} rows (est. ${Math.round(expected * (node.loops ?? 1))})`;
}

function Node({ node, depth, rootMs }: { node: PlanNode; depth: number; rootMs: number }) {
  const [open, setOpen] = useState(depth < 4);
  const own = node.self_ms ?? 0;
  const share = rootMs > 0 ? Math.min(1, own / rootMs) : 0;
  const details = DETAIL_KEYS.filter((k) => node.details[k] != null).map(
    (k) => [k, node.details[k]] as const,
  );
  if (node.sort_method) details.push(["Sort Method", `${node.sort_method} (${node.sort_space_type})`]);
  const expandable = node.children.length > 0 || details.length > 0;
  const help = explainNode(node.node_type);
  return (
    <li>
      <div className="relative rounded py-1 pr-2" style={{ paddingLeft: depth * 14 }}>
        <div
          aria-hidden
          className="absolute inset-y-0.5 left-0 rounded bg-accent-soft"
          style={{ width: `${Math.max(share * 100, 0.5)}%` }}
        />
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={expandable ? open : undefined}
          title={help}
          className="relative flex w-full items-start gap-1.5 text-left"
        >
          <ChevronRight
            aria-hidden
            className={`mt-0.5 size-3.5 shrink-0 text-faint transition-transform ${open ? "rotate-90" : ""} ${expandable ? "" : "invisible"}`}
          />
          <span className="min-w-0 flex-1">
            <span className={`font-medium ${TONE[nodeTone(node.node_type)]}`}>{node.node_type}</span>{" "}
            <span className="text-muted">{describe(node)}</span>
          </span>
          <span className="shrink-0 text-faint tabular">
            {rows(node)}
            {node.self_ms != null ? ` · ${ms(node.self_ms, 2)}` : ""}
          </span>
        </button>
        {open && details.length ? (
          <dl className="relative mt-1 ml-5 grid grid-cols-[auto_1fr] gap-x-2 text-faint">
            {details.map(([k, v]) => (
              <div key={k} className="contents">
                <dt>{k}</dt>
                <dd className="font-mono break-all">{Array.isArray(v) ? v.join(", ") : String(v)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
      {open && node.children.length ? (
        <ul>
          {node.children.map((child, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: plan children have no ids
            <Node key={i} node={child} depth={depth + 1} rootMs={rootMs} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** A plan as a tree; each node's bar is its own share of the execution time. */
export function PlanTree({ plan }: { plan: PlanResult }) {
  if (!plan.root) return null;
  const rootMs = (plan.root.actual_total_ms ?? 0) * (plan.root.loops ?? 1);
  return (
    <ul className="text-xs" aria-label="Query plan">
      <Node node={plan.root} depth={0} rootMs={rootMs} />
    </ul>
  );
}
