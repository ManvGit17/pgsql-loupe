import type { PlanResult, RequestDetail, RequestSummary } from "./types";

/** The URL prefix the panel is served under (`/__lens` unless configured otherwise). */
export function prefix(): string {
  return document.getElementById("root")?.dataset.prefix ?? "/__lens";
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = "";
    try {
      detail = ((await response.json()) as { error?: string }).error ?? "";
    } catch {
      // not JSON
    }
    throw new Error(`${response.status} ${detail}`.trim());
  }
  return (await response.json()) as T;
}

export async function listRequests(): Promise<RequestSummary[]> {
  const data = await json<{ requests: RequestSummary[] }>(
    await fetch(`${prefix()}/api/requests`, { cache: "no-store" }),
  );
  return data.requests;
}

export async function getRequest(id: string): Promise<RequestDetail> {
  return json<RequestDetail>(
    await fetch(`${prefix()}/api/requests/${encodeURIComponent(id)}`, { cache: "no-store" }),
  );
}

/** Replays one statement under EXPLAIN on the server. The X-Lens header is required. */
export async function explainStatement(id: string, index: number): Promise<PlanResult> {
  return json<PlanResult>(
    await fetch(`${prefix()}/api/requests/${encodeURIComponent(id)}/statements/${index}/explain`, {
      method: "POST",
      headers: { "X-Lens": "1" },
    }),
  );
}
