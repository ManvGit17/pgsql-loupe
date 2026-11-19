/** Shapes served by /__lens/api (see src/pgsql_loupe/asgi/serialize.py). */

export interface RequestSummary {
  id: string;
  method: string;
  path: string;
  mode: "trace" | "plan";
  status: number | null;
  started_at: string;
  duration_ms: number | null;
  statement_count: number;
  db_ms: number | null;
  db_share: number | null;
  error_count: number;
  nplus1_count: number;
  duplicate_count: number;
  exception: string | null;
  plan_note: string | null;
}

export interface CallSite {
  file: string;
  line: number;
  function: string;
}

export interface PlanNode {
  node_type: string;
  relation: string | null;
  index: string | null;
  alias: string | null;
  join_type: string | null;
  startup_cost: number;
  total_cost: number;
  plan_rows: number;
  actual_rows: number | null;
  loops: number | null;
  actual_total_ms: number | null;
  rows_removed_by_filter: number | null;
  shared_hit_blocks: number | null;
  shared_read_blocks: number | null;
  temp_written_blocks: number | null;
  sort_method: string | null;
  sort_space_type: string | null;
  hash_batches: number | null;
  self_ms: number | null;
  details: Record<string, unknown>;
  children: PlanNode[];
}

export interface TriggerRun {
  name: string | null;
  relation: string | null;
  constraint: string | null;
  calls: number | null;
  time_ms: number | null;
}

export interface Flag {
  kind: "seq_scan" | "row_estimate" | "spill";
  message: string;
  node_type: string;
  relation: string | null;
}

export interface PlanResult {
  mode: "analyze" | "plain" | "skipped" | "error";
  root: PlanNode | null;
  planning_ms: number | null;
  execution_ms: number | null;
  triggers: TriggerRun[];
  flags: Flag[];
  error: string | null;
  sqlstate: string | null;
}

export interface Statement {
  index: number;
  sql: string;
  params: string[] | Record<string, string> | null;
  kind: "execute" | "executemany" | "stream" | "copy" | "declare";
  start_ms: number;
  duration_ms: number | null;
  rowcount: number | null;
  param_sets: number | null;
  error: string | null;
  sqlstate: string | null;
  error_message: string | null;
  tx_status: string | null;
  backend_pid: number | null;
  call_site: CallSite | null;
  fingerprint: string;
  explain: "read" | "write" | "none";
  plan: PlanResult | null;
}

export interface RepeatedShape {
  fingerprint: string;
  count: number;
  distinct_values: number;
  total_ms: number;
  statements: number[];
  call_sites: string[];
}

export interface Duplicate {
  sql: string;
  count: number;
  total_ms: number;
  statements: number[];
}

export interface Analysis {
  summary: {
    statement_count: number;
    db_ms: number;
    request_ms: number | null;
    db_share: number | null;
    error_count: number;
    slow_statements: number[];
  };
  nplus1: RepeatedShape[];
  duplicates: Duplicate[];
}

export interface RequestDetail extends RequestSummary {
  analysis: Analysis;
  statements: Statement[];
}
