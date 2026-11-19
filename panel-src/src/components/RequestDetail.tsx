import { useEffect, useState } from "react";
import { ms, percent, plural } from "../lib/format";
import type { PlanResult, RequestDetail as Detail } from "../types";
import { StatementRow } from "./StatementRow";
import { Warnings } from "./Warnings";

function marksFor(detail: Detail): Map<number, string[]> {
  const marks = new Map<number, string[]>();
  const add = (i: number, m: string) => marks.set(i, [...(marks.get(i) ?? []), m]);
  for (const n of detail.analysis.nplus1) for (const i of n.statements) add(i, "N+1");
  for (const d of detail.analysis.duplicates) for (const i of d.statements) add(i, "dup");
  for (const i of detail.analysis.summary.slow_statements) add(i, "slow");
  return marks;
}

export function RequestDetail({
  detail,
  onPlan,
}: {
  detail: Detail;
  onPlan: (index: number, plan: PlanResult) => void;
}) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  useEffect(() => setOpen(new Set()), [detail.id]);
  const totalMs = Math.max(
    detail.duration_ms ?? 0,
    ...detail.statements.map((s) => s.start_ms + (s.duration_ms ?? 0)),
  );
  const marks = marksFor(detail);

  function toggle(index: number) {
    const next = new Set(open);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setOpen(next);
  }

  function show(index: number) {
    setOpen(new Set(open).add(index));
    requestAnimationFrame(() =>
      document.getElementById(`statement-${index}`)?.scrollIntoView({ block: "center" }),
    );
  }

  return (
    <article className="flex flex-col gap-5" aria-label={`${detail.method} ${detail.path}`}>
      <header>
        <h2 className="font-mono text-lg break-all">
          {detail.method} {detail.path}
        </h2>
        <p className="mt-1 text-sm text-muted tabular">
          {detail.status ?? "no status"} · {ms(detail.duration_ms)} total ·{" "}
          {plural(detail.statement_count, "statement")} · {ms(detail.db_ms)} in the database (
          {percent(detail.db_share)})
          {detail.exception ? ` · raised ${detail.exception}` : ""}
        </p>
        {detail.plan_note ? <p className="mt-1 text-xs text-faint">Plans: {detail.plan_note}</p> : null}
      </header>
      <section aria-labelledby="warnings-title">
        <h3 id="warnings-title" className="mb-2 text-sm font-semibold">
          Warnings
        </h3>
        <Warnings detail={detail} onShow={show} />
      </section>
      <section aria-labelledby="statements-title">
        <h3 id="statements-title" className="mb-2 text-sm font-semibold">
          Statements
        </h3>
        <ol className="flex flex-col gap-1.5">
          {detail.statements.map((s) => (
            <div id={`statement-${s.index}`} key={s.index}>
              <StatementRow
                requestId={detail.id}
                statement={s}
                totalMs={totalMs}
                marks={marks.get(s.index) ?? []}
                open={open.has(s.index)}
                onToggle={() => toggle(s.index)}
                onPlan={(plan) => onPlan(s.index, plan)}
              />
            </div>
          ))}
        </ol>
      </section>
    </article>
  );
}
