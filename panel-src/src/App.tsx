import { Database, Moon, RefreshCw, Sun } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getRequest, listRequests } from "./api";
import { RequestDetail } from "./components/RequestDetail";
import { RequestList } from "./components/RequestList";
import type { PlanResult, RequestDetail as Detail, RequestSummary } from "./types";

type Theme = "light" | "dark";

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem("pgsql-loupe-theme");
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function initialTheme(): Theme {
  return storedTheme() ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}

function idFromHash(): string | null {
  return decodeURIComponent(location.hash.slice(1)) || null;
}

export function App() {
  const [requests, setRequests] = useState<RequestSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(idFromHash);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [live, setLive] = useState(true);
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const refresh = useCallback(async () => {
    try {
      setRequests(await listRequests());
      setError("");
    } catch (e) {
      setError(`Could not load requests: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void refresh();
    if (!live) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 2000);
    return () => clearInterval(timer);
  }, [live, refresh]);

  useEffect(() => {
    const onHash = () => setSelected(idFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!selected && requests[0]) setSelected(requests[0].id);
  }, [requests, selected]);

  const selectedSummary = requests.find((r) => r.id === selected);
  // Re-fetch when the request is selected, and while it is still running.
  const version = selectedSummary
    ? `${selectedSummary.duration_ms}-${selectedSummary.statement_count}-${selectedSummary.plan_note}`
    : "";
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    getRequest(selected)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setDetail(null);
          setError(`Could not load request ${selected}: ${e.message}`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected, version]);

  function select(id: string) {
    history.replaceState(null, "", `#${encodeURIComponent(id)}`);
    setSelected(id);
  }

  function updatePlan(index: number, plan: PlanResult) {
    setDetail((d) =>
      d ? { ...d, statements: d.statements.map((s) => (s.index === index ? { ...s, plan } : s)) } : d,
    );
  }

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem("pgsql-loupe-theme", next);
    } catch {
      // storage unavailable: the choice lasts for this page only
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-2.5">
        <Database aria-hidden className="size-5 text-accent" />
        <h1 className="flex-1 text-base font-semibold">pgsql-loupe</h1>
        <label className="flex items-center gap-1.5 text-xs text-muted">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Live
        </label>
        <button
          type="button"
          onClick={() => void refresh()}
          aria-label="Refresh the request list"
          className="rounded p-1.5 text-muted hover:bg-sunk hover:text-ink"
        >
          <RefreshCw aria-hidden className="size-4" />
        </button>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          className="rounded p-1.5 text-muted hover:bg-sunk hover:text-ink"
        >
          {theme === "dark" ? <Sun aria-hidden className="size-4" /> : <Moon aria-hidden className="size-4" />}
        </button>
      </header>
      {error ? (
        <p role="alert" className="border-b border-line bg-surface px-4 py-2 text-sm text-bad">
          {error}
        </p>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav
          aria-label="Requests"
          className="max-h-[40vh] shrink-0 overflow-y-auto border-b border-line bg-surface md:max-h-none md:w-80 md:border-r md:border-b-0"
        >
          <RequestList requests={requests} selected={selected} onSelect={select} />
        </nav>
        <main className="min-w-0 flex-1 overflow-y-auto p-4">
          {detail && detail.id === selected ? (
            <RequestDetail detail={detail} onPlan={updatePlan} />
          ) : (
            <p className="text-sm text-muted">{requests.length ? "Select a request." : ""}</p>
          )}
        </main>
      </div>
    </div>
  );
}
