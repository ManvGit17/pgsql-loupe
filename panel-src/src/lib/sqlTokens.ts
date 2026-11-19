/** Minimal SQL highlighting: split text into typed tokens. Every character is kept. */

export type TokenKind = "comment" | "string" | "param" | "number" | "keyword" | "text";

const KEYWORDS = new Set(
  `select from where and or not in is null as join left right inner full cross lateral on using
  group by order limit offset having with union all distinct insert into values update set delete
  returning case when then else end exists cast coalesce array any unnest conflict do nothing
  begin commit rollback true false asc desc nulls last first over partition filter within merge
  matched explain analyze buffers format json copy stdin stdout for share`
    .split(/\s+/)
    .filter(Boolean),
);

const TOKEN =
  /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*'?)|(\$\d+|%\([A-Za-z_][A-Za-z0-9_]*\)[sbt]|%[sbt]|\{[A-Za-z_][^}]*\})|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_$]*)|(\s+|[\s\S])/g;

export function tokenizeSql(sql: string): { kind: TokenKind; text: string }[] {
  const out: { kind: TokenKind; text: string }[] = [];
  for (const m of sql.matchAll(TOKEN)) {
    const [text, comment, str, param, num, word] = m;
    let kind: TokenKind = "text";
    if (comment) kind = "comment";
    else if (str) kind = "string";
    else if (param) kind = "param";
    else if (num) kind = "number";
    else if (word && KEYWORDS.has(word.toLowerCase())) kind = "keyword";
    const last = out[out.length - 1];
    if (kind === "text" && last?.kind === "text") last.text += text;
    else out.push({ kind, text });
  }
  return out;
}
