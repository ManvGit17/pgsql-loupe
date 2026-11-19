import { describe, expect, it } from "vitest";
import { copyableSql, firstLine, ms, paramPairs, percent, shortSite, timelineBar } from "./format";
import { explainNode, nodeTone } from "./planNodes";
import { tokenizeSql } from "./sqlTokens";

describe("format", () => {
  it("formats durations", () => {
    expect(ms(null)).toBe("–");
    expect(ms(1.234)).toBe("1.2 ms");
    expect(ms(1234)).toBe("1.23 s");
    expect(percent(0.256)).toBe("26%");
  });

  it("pairs positional and named parameters", () => {
    expect(paramPairs(["1", "'a'"])).toEqual([["$1", "1"], ["$2", "'a'"]]);
    expect(paramPairs({ id: "7" })).toEqual([["id", "7"]]);
    expect(paramPairs(null)).toEqual([]);
  });

  it("copies SQL with parameters as comments", () => {
    expect(copyableSql({ sql: " SELECT %(id)s ", params: { id: "7" } })).toBe(
      "-- id = 7\nSELECT %(id)s",
    );
  });

  it("shortens call sites and skips comment lines", () => {
    expect(shortSite(String.raw`D:\app\api\routes.py:54`)).toBe("api/routes.py:54");
    expect(shortSite({ file: "/srv/app.py", line: 3, function: "f" })).toBe("srv/app.py:3");
    expect(firstLine("-- name: x\n  SELECT 1\nFROM t")).toBe("SELECT 1");
  });

  it("places timeline bars inside 0..100", () => {
    expect(timelineBar({ start_ms: 50, duration_ms: 25 }, 100)).toEqual({ left: 50, width: 25 });
    expect(timelineBar({ start_ms: 99, duration_ms: 50 }, 100).width).toBeCloseTo(1);
    expect(timelineBar({ start_ms: 0, duration_ms: 0 }, 100).width).toBe(0.4);
    expect(timelineBar({ start_ms: 0, duration_ms: 1 }, 0)).toEqual({ left: 0, width: 0 });
  });
});

describe("plan nodes", () => {
  it("explains common node types, including parallel ones", () => {
    expect(explainNode("Seq Scan")).toMatch(/every row/);
    expect(explainNode("Parallel Seq Scan")).toBe(explainNode("Seq Scan"));
    expect(explainNode("Something New")).toBeUndefined();
    expect([nodeTone("Index Scan"), nodeTone("Seq Scan"), nodeTone("Sort")]).toEqual([
      "good",
      "warn",
      "plain",
    ]);
  });
});

describe("sql tokens", () => {
  it("keeps every character and classifies tokens", () => {
    const sql = "SELECT 'a''b', 42, %(id)s, $1 -- note\nFROM t";
    const tokens = tokenizeSql(sql);
    expect(tokens.map((t) => t.text).join("")).toBe(sql);
    const kinds = tokens.filter((t) => t.kind !== "text").map((t) => `${t.kind}:${t.text}`);
    expect(kinds).toEqual([
      "keyword:SELECT",
      "string:'a''b'",
      "number:42",
      "param:%(id)s",
      "param:$1",
      "comment:-- note",
      "keyword:FROM",
    ]);
  });
});
