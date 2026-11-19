import { useRef } from "react";
import { ms } from "../lib/format";
import type { RequestSummary } from "../types";

function statusTone(status: number | null): string {
  if (status == null || status >= 500) return "text-bad";
  if (status >= 400) return "text-warn";
  return "text-good";
}

/** Traced requests, newest first. Arrow keys move between them. */
export function RequestList({
  requests,
  selected,
  onSelect,
}: {
  requests: RequestSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const next =
      event.key === "ArrowDown" ? index + 1 : event.key === "ArrowUp" ? index - 1 : null;
    if (next == null || next < 0 || next >= requests.length) return;
    event.preventDefault();
    const target = requests[next];
    if (target) {
      onSelect(target.id);
      refs.current[next]?.focus();
    }
  }

  if (!requests.length) {
    return (
      <p className="p-4 text-sm text-muted">
        No traced requests yet. Open any page of your app with <code className="font-mono">?lens=1</code>{" "}
        (or <code className="font-mono">?lens=plan</code> for query plans).
      </p>
    );
  }
  return (
    <ul className="flex flex-col" aria-label="Traced requests">
      {requests.map((r, i) => (
        <li key={r.id}>
          <button
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            onClick={() => onSelect(r.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            aria-current={r.id === selected ? "true" : undefined}
            className={`flex w-full flex-col gap-0.5 border-b border-line px-3 py-2 text-left hover:bg-sunk ${r.id === selected ? "bg-accent-soft" : ""}`}
          >
            <span className="flex items-center gap-2">
              <span className="text-xs font-semibold text-muted">{r.method}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-sm">{r.path}</span>
              <span className={`text-xs tabular ${statusTone(r.status)}`}>{r.status ?? "…"}</span>
            </span>
            <span className="flex items-center gap-2 text-xs text-faint tabular">
              <span>
                {r.statement_count} SQL · {ms(r.db_ms)}
              </span>
              {r.mode === "plan" ? <span className="text-accent">plans</span> : null}
              {r.nplus1_count ? <span className="text-warn">N+1</span> : null}
              {r.duplicate_count ? <span className="text-warn">dup</span> : null}
              {r.error_count ? <span className="text-bad">{r.error_count} err</span> : null}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
