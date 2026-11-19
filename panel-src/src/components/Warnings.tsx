import { AlertTriangle } from "lucide-react";
import { ms, plural, shortSite } from "../lib/format";
import type { RequestDetail } from "../types";

/** N+1 shapes, duplicates, slow statements and plan flags, each linking to statements. */
export function Warnings({
  detail,
  onShow,
}: {
  detail: RequestDetail;
  onShow: (index: number) => void;
}) {
  const { nplus1, duplicates, summary } = detail.analysis;
  const flagged = detail.statements.filter((s) => s.plan?.flags.length);
  if (!nplus1.length && !duplicates.length && !summary.slow_statements.length && !flagged.length) {
    return <p className="text-sm text-good">No warnings for this request.</p>;
  }
  const link = (i: number) => (
    <button
      key={i}
      type="button"
      onClick={() => onShow(i)}
      className="rounded bg-sunk px-1 font-mono text-xs text-accent hover:underline"
    >
      #{i}
    </button>
  );
  return (
    <ul className="flex flex-col gap-2 text-sm" aria-label="Warnings">
      {nplus1.map((n) => (
        <li key={n.fingerprint} className="rounded-lg border border-warn/40 bg-surface p-3">
          <p className="flex items-center gap-1.5 font-medium text-warn">
            <AlertTriangle aria-hidden className="size-4" />
            N+1: the same query ran {n.count} times ({ms(n.total_ms)})
          </p>
          <p className="mt-1 font-mono text-xs break-all text-muted">{n.fingerprint}</p>
          <p className="mt-1 text-xs text-faint">
            from {n.call_sites.map(shortSite).join(", ") || "unknown code"} · statements{" "}
            <span className="inline-flex flex-wrap gap-1">{n.statements.slice(0, 12).map(link)}</span>
            {n.statements.length > 12 ? " …" : ""}
          </p>
        </li>
      ))}
      {duplicates.map((d) => (
        <li key={d.sql + d.statements.join()} className="rounded-lg border border-line bg-surface p-3">
          <p className="font-medium">Exact duplicate: {plural(d.count, "run")} with the same values</p>
          <p className="mt-1 text-xs text-faint">
            statements <span className="inline-flex flex-wrap gap-1">{d.statements.map(link)}</span>
          </p>
        </li>
      ))}
      {summary.slow_statements.length ? (
        <li className="rounded-lg border border-line bg-surface p-3">
          <p className="font-medium">Slow statements</p>
          <p className="mt-1 inline-flex flex-wrap gap-1">{summary.slow_statements.map(link)}</p>
        </li>
      ) : null}
      {flagged.map((s) => (
        <li key={`flag-${s.index}`} className="rounded-lg border border-line bg-surface p-3">
          <p className="font-medium">Plan warnings on {link(s.index)}</p>
          <ul className="mt-1 text-xs text-warn">
            {s.plan?.flags.map((f, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: flags have no ids
              <li key={i}>{f.message}</li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
