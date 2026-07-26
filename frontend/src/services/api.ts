/**
 * Live API client for FastAPI `/api/v1` (Phase 9).
 * Types mirror backend contract-v1; no localStorage mocks.
 */

export enum IntentType {
  BROAD_EXPLORATION = "broad_exploration",
  SIMPLE_LOOKUP = "simple_lookup",
  THRESHOLD_AGGREGATION = "threshold_aggregation",
  FEATURE_COMPARISON = "feature_comparison",
  PATTERN_SEARCH = "pattern_search",
  ENTITY_INVESTIGATION = "entity_investigation",
  TRANSACTION_SCORING = "transaction_scoring",
  EXPLANATION_REQUEST = "explanation_request",
}

export enum RouteType {
  SIMPLE_LOOKUP = "simple_lookup",
  FEATURE_ONLY = "feature_only",
  FULL_INVESTIGATION = "full_investigation",
}

export enum ToolName {
  SQL_LOOKUP = "sql_lookup",
  EDA = "eda",
  FEATURE_ENGINEERING = "feature_engineering",
  ANOMALY_DETECTION = "anomaly_detection",
  GRAPH_ANALYSIS = "graph_analysis",
  RETRIEVAL = "retrieval",
  RISK_CLASSIFICATION = "risk_classification",
  VERIFICATION = "verification",
  ESCALATION = "escalation",
  EXPLANATION = "explanation",
}

export type AlertStatus = "open" | "in_review" | "escalated" | "dismissed" | "closed";

export interface SkippedTool {
  tool: string;
  reason: string;
}

export interface ExecutionSummary {
  query: string;
  detected_intent: string;
  route: string;
  filters: Record<string, unknown>;
  plan?: {
    strategy: string;
    planner_version: string;
    steps: Array<{
      step_id: string;
      tool: string;
      operation: string;
      parameters: Record<string, unknown>;
      depends_on?: string[];
      reason: string;
    }>;
  } | null;
  tools_invoked: string[];
  tools_skipped: SkippedTool[];
  fallbacks: string[];
  warnings: string[];
}

export interface InformationalResult {
  result_type: "informational";
  entity_type: string | null;
  entity_id: string | null;
  summary: string;
  data: Record<string, unknown>;
  evidence_refs: string[];
}

export interface FlaggedResult {
  result_type: "flagged";
  entity_type: string;
  entity_id: string;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  confidence: number;
  reasons: string[];
  escalation_action: "monitor" | "review" | "report";
  evidence_refs: string[];
}

export type ResultItem = InformationalResult | FlaggedResult;

export interface EvidenceReference {
  evidence_id: string;
  tool: string;
  kind: string;
  json_path: string;
  label: string;
}

export interface ToolResult {
  tool: string;
  operation: string;
  status: string;
  scope: Record<string, unknown>;
  data: Record<string, unknown>;
  evidence: EvidenceReference[];
  warnings: string[];
  duration_ms: number;
  produced_at: string;
  provenance: {
    source: string;
    query_or_version: string;
    dataset_version?: string | null;
    policy_version?: string | null;
  };
  error?: { code: string; message: string; retryable: boolean } | null;
}

export interface ChartSpec {
  chart_id: string;
  chart_type: "bar" | "line" | "histogram" | "scatter" | "table";
  title: string;
  data: { labels?: string[]; values?: number[]; [key: string]: unknown };
  x_label?: string | null;
  y_label?: string | null;
  evidence_refs: string[];
}

export interface FinalResponse {
  contract_version: "v1";
  request_id: string;
  generated_at: string;
  execution_summary: ExecutionSummary;
  results: ResultItem[];
  supporting_evidence: ToolResult[];
  charts: ChartSpec[];
  answer: string;
  status?: "completed" | "partial" | "failed";
  clarification?: string | null;
}

export interface AuditLog {
  timestamp: string;
  reviewer: string;
  transition: string;
  reason?: string;
}

export interface Alert {
  id: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  risk_score: number;
  escalation_action: string;
  entity_type: "customer" | "transaction" | "account";
  entity_id: string;
  opened_at: string;
  status: AlertStatus;
  age_description: string;
  evidence_snapshot_ref: string;
  policy_version: string;
  results: ResultItem[];
  supporting_evidence: ToolResult[];
  audit_history: AuditLog[];
}

export interface CustomerProfile {
  id: string;
  name: string;
  country: string;
  segment: string;
  status: string;
  created_at: string;
  risk_rating: "LOW" | "MEDIUM" | "HIGH";
  kyc_occupation: string;
  kyc_income_usd: string;
  kyc_risk_score: number | null;
  recent_transactions: Array<{
    id: string;
    amount: number;
    currency: string;
    date: string;
    status: string;
  }>;
  alerts: Array<{ id: string; status: string; date: string }>;
}

/** Fixed demo clock aligned with scenario_catalog.v1 as_of / seed window. */
export const DEMO_AS_OF = "2026-07-25T00:00:00Z";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body?.detail?.message || body?.message || body?.detail || detail;
      if (typeof detail !== "string") detail = JSON.stringify(detail);
    } catch {
      /* ignore */
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

function ageDescription(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const hours = Math.max(0, Math.floor(ms / 3_600_000));
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function mapAlert(raw: Record<string, unknown>): Alert {
  const history = Array.isArray(raw.history) ? raw.history : [];
  return {
    id: String(raw.alert_id),
    risk_level: String(raw.risk_tier || "LOW").toUpperCase() as Alert["risk_level"],
    risk_score: Number(raw.risk_score ?? 0),
    escalation_action: String(raw.escalation_action || "monitor"),
    entity_type: String(raw.entity_type) as Alert["entity_type"],
    entity_id: String(raw.entity_id),
    opened_at: String(raw.created_at),
    status: String(raw.status) as AlertStatus,
    age_description: ageDescription(String(raw.created_at)),
    evidence_snapshot_ref: String(raw.evidence_snapshot_ref || ""),
    policy_version: String(raw.policy_version || ""),
    results: [],
    supporting_evidence: [],
    audit_history: history.map((event: Record<string, unknown>) => ({
      timestamp: String(event.timestamp),
      reviewer: String(event.reviewer_id),
      transition: `${event.from_status ?? "∅"} → ${event.to_status}`,
      reason: String(event.reason || ""),
    })),
  };
}

function mapQueryToFinal(raw: Record<string, unknown>): FinalResponse {
  const summary = (raw.execution_summary || {}) as ExecutionSummary;
  return {
    contract_version: "v1",
    request_id: String(raw.request_id),
    generated_at: new Date().toISOString(),
    execution_summary: {
      query: summary.query || "",
      detected_intent: summary.detected_intent || "",
      route: summary.route || "",
      filters: (summary.filters || {}) as Record<string, unknown>,
      plan: summary.plan ?? null,
      tools_invoked: summary.tools_invoked || [],
      tools_skipped: summary.tools_skipped || [],
      fallbacks: summary.fallbacks || [],
      warnings: summary.warnings || [],
    },
    results: (raw.results as ResultItem[]) || [],
    supporting_evidence: (raw.supporting_evidence as ToolResult[]) || (raw.tool_results as ToolResult[]) || [],
    charts: (raw.charts as ChartSpec[]) || [],
    answer: String(raw.answer || ""),
    status: (raw.status as FinalResponse["status"]) || "completed",
    clarification: (raw.clarification as string | null) ?? null,
  };
}

export const api = {
  async getHealth(): Promise<{ status: string; environment?: string }> {
    return request("/api/v1/health");
  },

  async executeQuery(query: string): Promise<FinalResponse> {
    const raw = await request<Record<string, unknown>>("/api/v1/query", {
      method: "POST",
      body: JSON.stringify({
        query,
        as_of: DEMO_AS_OF,
        filters: {},
      }),
    });
    return mapQueryToFinal(raw);
  },

  async getAlerts(): Promise<Alert[]> {
    const raw = await request<{ items: Record<string, unknown>[] }>("/api/v1/alerts?limit=100&offset=0");
    return (raw.items || []).map(mapAlert);
  },

  async updateAlertStatus(
    alertId: string,
    status: AlertStatus,
    reviewerId: string,
    reason?: string,
  ): Promise<Alert> {
    const raw = await request<Record<string, unknown>>(`/api/v1/alerts/${encodeURIComponent(alertId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        status,
        reviewer_id: reviewerId,
        reason: reason || "status update",
        request_id: `ui-${Date.now()}`,
      }),
    });
    return mapAlert(raw);
  },

  async createAlertFromQuery(
    entityType: "customer" | "transaction",
    entityId: string,
    results: ResultItem[],
    _evidence: ToolResult[],
  ): Promise<Alert> {
    const flagged = results.find((r) => r.result_type === "flagged") as FlaggedResult | undefined;
    const severity =
      flagged?.risk_level === "HIGH" ? "high" : flagged?.risk_level === "MEDIUM" ? "medium" : "low";
    const windowEnd = DEMO_AS_OF;
    const windowStart = "2026-04-26T00:00:00Z";
    const raw = await request<Record<string, unknown>>("/api/v1/alerts", {
      method: "POST",
      body: JSON.stringify({
        entity_type: entityType,
        entity_id: entityId,
        finding_code: "UI_MANUAL_ALERT",
        severity,
        evidence_snapshot_ref: `ui:${entityId}`,
        policy_version: "risk_scoring.v1",
        investigation_window_start: windowStart,
        investigation_window_end: windowEnd,
        request_id: `ui-create-${Date.now()}`,
      }),
    });
    return mapAlert(raw);
  },

  async getCustomersList(): Promise<CustomerProfile[]> {
    const raw = await request<{ items: Array<{ customer_id: string; created_at: string; status: string }> }>(
      "/api/v1/customers?limit=100&offset=0",
    );
    return (raw.items || []).map((item) => ({
      id: item.customer_id,
      name: item.customer_id,
      country: "—",
      segment: "—",
      status: item.status,
      created_at: item.created_at,
      risk_rating: "LOW",
      kyc_occupation: "—",
      kyc_income_usd: "—",
      kyc_risk_score: null,
      recent_transactions: [],
      alerts: [],
    }));
  },

  async getCustomerDetails(customerId: string): Promise<CustomerProfile> {
    const customer = await request<{ customer_id: string; created_at: string; status: string }>(
      `/api/v1/customers/${encodeURIComponent(customerId)}`,
    );
    const alerts = await this.getAlerts();
    const linked = alerts
      .filter((a) => a.entity_type === "customer" && a.entity_id === customerId)
      .map((a) => ({ id: a.id, status: a.status, date: a.opened_at }));
    return {
      id: customer.customer_id,
      name: customer.customer_id,
      country: "—",
      segment: "synthetic runtime record",
      status: customer.status,
      created_at: customer.created_at,
      risk_rating: linked.some((a) => a.status === "open" || a.status === "escalated") ? "HIGH" : "LOW",
      kyc_occupation: "Not stored in runtime API (see investigation tools)",
      kyc_income_usd: "—",
      kyc_risk_score: null,
      recent_transactions: [],
      alerts: linked,
    };
  },
};
