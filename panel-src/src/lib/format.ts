import type { CallSite, Statement } from "../types";

export function ms(value: number | null | undefined, digits = 1): string {
  if (value == null) return "–";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${value.toFixed(digits)} ms`;
}

export function percent(share: number | null | undefined): string {
  return share == null ? "–" : `${Math.round(share * 100)}%`;
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}

/** `app.py:54` from a full path, keeping the last folder for context: `api/app.py:54`. */
export function shortSite(site: CallSite | string): string {
  const text = typeof site === "string" ? site : `${site.file}:${site.line}`;
  const parts = text.split(/[\\/]/);
  return parts.slice(-2).join("/");
}

/** First line of the SQL, for one-line lists. */
export function firstLine(sql: string): string {
  const line = sql
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l && !l.startsWith("--"));
  return line ?? sql.trim();
}

/** Parameters as `name = value` (named) or `$n = value` (positional) pairs. */
export function paramPairs(params: Statement["params"]): [string, string][] {
  if (!params) return [];
  if (Array.isArray(params)) return params.map((value, i) => [`$${i + 1}`, value]);
  return Object.entries(params);
}

/** A statement as text to paste into psql: its parameters as comments above the SQL. */
export function copyableSql(s: Pick<Statement, "sql" | "params">): string {
  const header = paramPairs(s.params).map(
    ([name, value]) => `-- ${name} = ${value.replace(/\s+/g, " ")}`,
  );
  return [...header, s.sql.trim()].join("\n");
}

/** Position and width (0..100) of a statement's bar on the request timeline. */
export function timelineBar(
  s: Pick<Statement, "start_ms" | "duration_ms">,
  totalMs: number,
): { left: number; width: number } {
  if (totalMs <= 0) return { left: 0, width: 0 };
  const left = Math.min(100, Math.max(0, (s.start_ms / totalMs) * 100));
  const width = Math.max(0.4, Math.min(100 - left, ((s.duration_ms ?? 0) / totalMs) * 100));
  return { left, width };
}

/** A transaction status from psycopg/asyncpg (IDLE, INTRANS, INERROR, ...) in words. */
export function transactionLabel(status: string | null): string | null {
  switch (status) {
    case "IDLE":
      return "outside a transaction";
    case "INTRANS":
      return "in a transaction";
    case "INERROR":
      return "in a failed transaction";
    case "ACTIVE":
      return "while another statement ran";
    default:
      return status ? status.toLowerCase() : null;
  }
}
