import { tokenizeSql, type TokenKind } from "../lib/sqlTokens";

const STYLE: Record<TokenKind, string> = {
  comment: "text-faint italic",
  string: "text-good",
  param: "rounded bg-accent-soft px-0.5 text-accent",
  number: "text-warn",
  keyword: "font-semibold text-accent",
  text: "",
};

export function SqlCode({ sql }: { sql: string }) {
  return (
    <pre className="overflow-x-auto rounded-lg bg-sunk p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink">
      <code>
        {tokenizeSql(sql).map((t, i) =>
          t.kind === "text" ? (
            t.text
          ) : (
            // biome-ignore lint/suspicious/noArrayIndexKey: tokens are positional
            <span key={i} className={STYLE[t.kind]}>
              {t.text}
            </span>
          ),
        )}
      </code>
    </pre>
  );
}
