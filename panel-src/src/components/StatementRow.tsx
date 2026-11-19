import { AlertTriangle, ChevronDown, Copy, Gauge, Zap } from "lucide-react";
import { useState } from "react";
import { explainStatement } from "../api";
import {
  copyableSql,
  firstLine,
  ms,
  paramPairs,
  plural,
  shortSite,
  timelineBar,
  transactionLabel,
} from "../lib/format";
import type { PlanResult, Statement } from "../types";
import { PlanTree } from "./PlanTree";
import { SqlCode } from "./SqlCode";

const MODE_LABEL: Record<PlanResult["mode"], string> = {
  analyze: "EXPLAIN ANALYZE",
  plain: "EXPLAIN (not executed)",
  skipped: "Not explained",
  error: "EXPLAIN failed",
};

function PlanSection({ plan }: { plan: PlanResult }) {
  return (
    <section aria-label="Plan" className="flex flex-col gap-2">
      <p className="text-xs font-semibold tracking-wide text-muted uppercase">
        {MODE_LABEL[plan.mode]}
        {plan.planning_ms != null ? ` · planned in ${ms(plan.planning_ms, 2)}` : ""}
        {plan.execution_ms != null ? ` · executed in ${ms(plan.execution_ms, 2)}` : ""}
      </p>
      {plan.error ? (
        <p className="text-xs text-bad">
          {plan.error}
          {plan.sqlstate ? ` (SQLSTATE ${plan.sqlstate})` : ""}
        </p>
      ) : null}
      {plan.flags.length ? (
        <ul className="flex flex-col gap-1">
          {plan.flags.map((f, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: flags have no ids
            <li key={i} className="flex items-start gap-1.5 text-xs text-warn">
              <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {f.message}
            </li>
          ))}
        </ul>
      ) : null}
      {plan.triggers.length ? (
        <div>
          <p className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">Triggers fired</p>
          <ul className="flex flex-col gap-1 text-xs">
            {plan.triggers.map((t) => (
              <li
                key={`${t.name}${t.relation}`}
                className="flex justify-between gap-2 rounded bg-sunk px-2 py-1"
              >
                <span className="truncate font-mono">
                  {t.constraint ? `${t.constraint} (foreign key)` : t.name}
                  {t.relation ? <span className="text-faint"> on {t.relation}</span> : null}
                </span>
                <span className="shrink-0 text-faint tabular">
                  {t.calls}× · {ms(t.time_ms, 2)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <PlanTree plan={plan} />
    </section>
  );
}

export function StatementRow({
  requestId,
  statement: s,
  totalMs,
  marks,
  open,
  onToggle,
  onPlan,
}: {
  requestId: string;
  statement: Statement;
  totalMs: number;
  marks: string[];
  open: boolean;
  onToggle: () => void;
  onPlan: (plan: PlanResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const bar = timelineBar(s, totalMs);
  const pairs = paramPairs(s.params);

  async function explain() {
    setBusy(true);
    setStatus("Running EXPLAIN…");
    try {
      onPlan(await explainStatement(requestId, s.index));
      setStatus("");
    } catch (error) {
      setStatus(`EXPLAIN request failed: ${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(copyableSql(s));
      setStatus("SQL copied, with its parameters as comments.");
    } catch {
      setStatus("Couldn't reach the clipboard.");
    }
  }

  return (
    <li className={`rounded-lg border ${s.error ? "border-bad/50" : "border-line"} bg-surface`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full flex-col gap-1 px-3 py-2 text-left"
      >
        <span className="flex w-full items-center gap-2">
          <ChevronDown
            aria-hidden
            className={`size-3.5 shrink-0 text-faint transition-transform ${open ? "" : "-rotate-90"}`}
          />
          <span className="w-6 shrink-0 text-xs text-faint tabular">#{s.index}</span>
          <span className="min-w-0 flex-1 truncate font-mono text-xs">{firstLine(s.sql)}</span>
          {marks.map((m) => (
            <span key={m} className="shrink-0 rounded bg-sunk px-1.5 text-[0.7rem] text-warn">
              {m}
            </span>
          ))}
          {s.plan?.triggers.length ? (
            <span className="flex shrink-0 items-center gap-0.5 text-[0.7rem] text-warn">
              <Zap aria-hidden className="size-3" />
              {s.plan.triggers.length}
            </span>
          ) : null}
          {s.error ? <span className="shrink-0 text-[0.7rem] text-bad">{s.error}</span> : null}
          <span className="shrink-0 text-xs text-faint tabular">{ms(s.duration_ms, 2)}</span>
        </span>
        <span aria-hidden className="relative block h-1.5 w-full rounded bg-sunk">
          <span
            className={`absolute inset-y-0 rounded ${s.error ? "bg-bad" : "bg-accent"}`}
            style={{ left: `${bar.left}%`, width: `${bar.width}%` }}
          />
        </span>
      </button>
      {open ? (
        <div className="flex flex-col gap-3 border-t border-line px-3 pt-2 pb-3">
          <div className="relative">
            <SqlCode sql={s.sql} />
            <button
              type="button"
              onClick={() => void copy()}
              aria-label={`Copy the SQL of statement ${s.index}`}
              className="absolute top-1.5 right-1.5 rounded bg-surface p-1 text-muted hover:text-ink"
            >
              <Copy aria-hidden className="size-3.5" />
            </button>
          </div>
          {pairs.length ? (
            <dl className="flex flex-wrap gap-1.5 text-xs" aria-label="Parameters">
              {pairs.map(([name, value]) => (
                <div key={name} className="rounded bg-sunk px-1.5 py-0.5 font-mono">
                  <dt className="inline text-faint">{name} = </dt>
                  <dd className="inline">{value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          <p className="text-xs text-faint tabular">
            {s.kind}
            {s.rowcount != null ? ` · ${plural(s.rowcount, "row")}` : ""}
            {s.param_sets != null ? ` · ${plural(s.param_sets, "parameter set")}` : ""}
            {transactionLabel(s.tx_status) ? ` · ${transactionLabel(s.tx_status)}` : ""}
            {s.call_site ? (
              <>
                {" · "}
                <span title={`${s.call_site.file}:${s.call_site.line}`} className="font-mono">
                  {shortSite(s.call_site)} in {s.call_site.function}()
                </span>
              </>
            ) : null}
          </p>
          {s.error ? (
            <p className="text-xs text-bad">
              {s.error_message}
              {s.sqlstate ? ` (SQLSTATE ${s.sqlstate})` : ""}
            </p>
          ) : null}
          {s.plan ? <PlanSection plan={s.plan} /> : null}
          {s.explain !== "none" ? (
            <div>
              <button
                type="button"
                onClick={() => void explain()}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded border border-line px-2 py-1 text-xs hover:bg-sunk disabled:opacity-50"
              >
                <Gauge aria-hidden className="size-3.5" />
                {s.plan ? "Explain again" : s.explain === "read" ? "Explain analyze" : "Explain"}
              </button>
            </div>
          ) : null}
          <p aria-live="polite" className="text-xs text-muted empty:hidden">
            {status}
          </p>
        </div>
      ) : null}
    </li>
  );
}
