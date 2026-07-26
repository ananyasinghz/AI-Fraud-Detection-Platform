/**
 * Reviewer-facing helpers for Investigate / Alerts / Customers.
 */

import type { FinalResponse, FlaggedResult, ToolResult } from "../services/api";
import { DEMO_AS_OF } from "../services/api";

export interface SqlTransactionRow {
  transaction_id: string;
  customer_id: string;
  amount_minor: number;
  currency: string;
  occurred_at: string;
  transaction_type: string;
  direction?: string;
  channel?: string;
}

export interface FeatureRow {
  tool: string;
  operation: string;
  entityHint: string;
  summary: string;
  details: Record<string, unknown>;
  windowRole?: string;
  values: Array<{ name: string; value: string; unit: string | null }>;
}

export interface ThresholdCohortRow {
  customer_id: string;
  transaction_count: number;
}

export interface ThresholdCohortView {
  customers: ThresholdCohortRow[];
  minimum_count: number;
  amount_max: string | null;
  total_matching: number;
}

export interface EdaCohortView {
  transaction_count: number | null;
  customer_count: number | null;
  amount_min_minor: number | null;
  amount_max_minor: number | null;
  amount_mean_minor: number | null;
  segment_counts: Record<string, number>;
  chart_titles: string[];
}

export interface SpendComparisonView {
  entityId: string;
  currentMinor: number;
  priorMinor: number;
  deltaMinor: number;
  ratio: number | null;
  elevated: boolean;
}

export interface ExplanationView {
  summary: string;
  reasons: string[];
  riskLevel: string;
  riskScore: number | null;
  confidence: number | null;
  escalationAction: string;
  recommendedAction: string;
  evidenceIds: string[];
  source: string;
  riskLevelExplanation: string;
}

const OPTIONAL_SKIP_TOOLS = new Set([
  "graph_analysis",
  "retrieval",
  "explanation",
]);

export function formatUsdFromMinor(amountMinor: number, currency = "USD"): string {
  const major = amountMinor / 100;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "USD",
    }).format(major);
  } catch {
    return `$${(major).toFixed(2)}`;
  }
}

function formatFeatureScalar(name: string, value: unknown, unit: string | null): string {
  if (value === null || value === undefined) return `${name}=—`;
  if (unit === "USD_minor" || unit === "usd_minor") {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isNaN(n)) return `${name}=${formatUsdFromMinor(n)}`;
  }
  const unitSuffix = unit ? ` (${unit})` : "";
  return `${name}=${String(value)}${unitSuffix}`;
}

function parseFeatureValues(
  featureResult: Record<string, unknown>,
): Array<{ name: string; value: string; unit: string | null }> {
  const raw = featureResult.values;
  const out: Array<{ name: string; value: string; unit: string | null }> = [];
  if (Array.isArray(raw)) {
    for (const item of raw.slice(0, 12)) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      const name = String(row.name || "value");
      const unit = row.unit != null ? String(row.unit) : null;
      out.push({
        name,
        value: formatFeatureScalar(name, row.value, unit).replace(`${name}=`, ""),
        unit,
      });
    }
    return out;
  }
  if (raw && typeof raw === "object") {
    for (const [k, v] of Object.entries(raw as Record<string, unknown>).slice(0, 12)) {
      out.push({ name: k, value: typeof v === "object" ? JSON.stringify(v) : String(v), unit: null });
    }
  }
  return out;
}

export function extractSqlTransactions(response: FinalResponse): SqlTransactionRow[] {
  const rows: SqlTransactionRow[] = [];
  for (const tool of response.supporting_evidence || []) {
    if (tool.tool !== "sql_lookup") continue;
    if (tool.operation === "count_by_customer") continue;
    const txs = tool.data?.transactions;
    if (!Array.isArray(txs)) continue;
    for (const raw of txs) {
      if (!raw || typeof raw !== "object") continue;
      const item = raw as Record<string, unknown>;
      rows.push({
        transaction_id: String(item.transaction_id || ""),
        customer_id: String(item.customer_id || ""),
        amount_minor: Number(item.amount_minor ?? 0),
        currency: String(item.currency || "USD"),
        occurred_at: String(item.occurred_at || ""),
        transaction_type: String(item.transaction_type || ""),
        direction: item.direction ? String(item.direction) : undefined,
        channel: item.channel ? String(item.channel) : undefined,
      });
    }
  }
  return rows;
}

export function extractThresholdCohort(response: FinalResponse): ThresholdCohortView | null {
  for (const tool of response.supporting_evidence || []) {
    if (tool.tool !== "sql_lookup" || tool.operation !== "count_by_customer") continue;
    if (tool.status !== "success") continue;
    const data = tool.data || {};
    const customersRaw = Array.isArray(data.customers) ? data.customers : [];
    const customers: ThresholdCohortRow[] = [];
    for (const raw of customersRaw) {
      if (!raw || typeof raw !== "object") continue;
      const row = raw as Record<string, unknown>;
      customers.push({
        customer_id: String(row.customer_id || ""),
        transaction_count: Number(row.transaction_count ?? 0),
      });
    }
    return {
      customers,
      minimum_count: Number(data.minimum_count ?? 10),
      amount_max: data.amount_max != null ? String(data.amount_max) : null,
      total_matching: Number(data.total_matching ?? customers.length),
    };
  }
  return null;
}

export function extractFeatureResults(response: FinalResponse): FeatureRow[] {
  const rows: FeatureRow[] = [];
  for (const tool of response.supporting_evidence || []) {
    if (tool.tool !== "feature_engineering") continue;
    if (tool.status !== "success" && tool.status !== "partial") continue;
    const data = tool.data || {};
    const featureResult = (data.feature_result || data) as Record<string, unknown>;
    const values = parseFeatureValues(featureResult);
    const summary =
      values.length > 0
        ? values.map((v) => `${v.name}=${v.value}`).join(", ")
        : tool.operation;
    const scope = tool.scope || {};
    const customers = Array.isArray(scope.customer_ids) ? scope.customer_ids : [];
    const windowRole =
      typeof data.window_role === "string"
        ? data.window_role
        : typeof featureResult.window_role === "string"
          ? String(featureResult.window_role)
          : undefined;
    rows.push({
      tool: tool.tool,
      operation: tool.operation,
      entityHint: customers.length ? String(customers[0]) : "—",
      summary,
      details: data,
      windowRole,
      values,
    });
  }
  return rows;
}

export function extractSpendComparison(response: FinalResponse): SpendComparisonView | null {
  const fromInfo = response.results.find((r) => r.result_type === "informational");
  if (fromInfo && fromInfo.data && typeof fromInfo.data === "object") {
    const data = fromInfo.data as Record<string, unknown>;
    const cmp = data.spend_comparison;
    if (cmp && typeof cmp === "object") {
      const c = cmp as Record<string, unknown>;
      if (c.current_minor != null && c.prior_minor != null) {
        const currentMinor = Number(c.current_minor);
        const priorMinor = Number(c.prior_minor);
        return {
          entityId: String(c.entity_id || "—"),
          currentMinor,
          priorMinor,
          deltaMinor: Number(c.delta_minor ?? currentMinor - priorMinor),
          ratio: c.ratio == null ? null : Number(c.ratio),
          elevated: Boolean(c.elevated),
        };
      }
    }
  }

  const features = extractFeatureResults(response);
  const totals = features
    .map((f) => {
      const total = f.values.find((v) => v.name === "transaction_total");
      if (!total) return null;
      const raw = f.details.feature_result as Record<string, unknown> | undefined;
      const arr = Array.isArray(raw?.values) ? raw!.values : [];
      let minor = 0;
      for (const item of arr) {
        if (!item || typeof item !== "object") continue;
        const row = item as Record<string, unknown>;
        if (String(row.name) === "transaction_total") {
          minor = Number(row.value ?? 0);
        }
      }
      return { role: f.windowRole || "", entityId: f.entityHint, minor };
    })
    .filter(Boolean) as Array<{ role: string; entityId: string; minor: number }>;

  const current = totals.find((t) => t.role === "current") || totals[0];
  const prior = totals.find((t) => t.role === "prior") || totals[1];
  if (!current || !prior || totals.length < 2) return null;
  const ratio = prior.minor > 0 ? current.minor / prior.minor : null;
  const elevated =
    (prior.minor > 0 && ratio != null && ratio >= 1.5) || (prior.minor === 0 && current.minor > 0);
  return {
    entityId: current.entityId,
    currentMinor: current.minor,
    priorMinor: prior.minor,
    deltaMinor: current.minor - prior.minor,
    ratio,
    elevated,
  };
}

export function extractEdaCohort(response: FinalResponse): EdaCohortView | null {
  for (const tool of response.supporting_evidence || []) {
    if (tool.tool !== "eda" || tool.operation !== "cohort_profile") continue;
    if (tool.status !== "success" && tool.status !== "partial") continue;
    const data = tool.data || {};
    const segments =
      data.segment_counts && typeof data.segment_counts === "object"
        ? (data.segment_counts as Record<string, number>)
        : {};
    const chartTitles = (response.charts || []).map((c) => c.title);
    return {
      transaction_count:
        typeof data.transaction_count === "number" ? data.transaction_count : null,
      customer_count: typeof data.customer_count === "number" ? data.customer_count : null,
      amount_min_minor:
        typeof data.amount_min_minor === "number" ? data.amount_min_minor : null,
      amount_max_minor:
        typeof data.amount_max_minor === "number" ? data.amount_max_minor : null,
      amount_mean_minor:
        typeof data.amount_mean_minor === "number" ? data.amount_mean_minor : null,
      segment_counts: segments,
      chart_titles: chartTitles,
    };
  }
  return null;
}

export function hasEdaEvidence(response: FinalResponse): boolean {
  return (response.supporting_evidence || []).some(
    (t) => t.tool === "eda" && (t.status === "success" || t.status === "partial"),
  );
}

export function hasPolicyContextOnly(response: FinalResponse): boolean {
  const warnings = response.execution_summary?.warnings || [];
  if (warnings.some((w) => /POLICY_CONTEXT_ONLY/i.test(w))) return true;
  return (response.supporting_evidence || []).some((t) =>
    (t.warnings || []).some((w) => /POLICY_CONTEXT_ONLY/i.test(w)),
  );
}

export function explanationFallbackCopy(response: FinalResponse): string {
  const route = response.execution_summary?.route || "";
  const intent = response.execution_summary?.detected_intent || "";
  if (hasEdaEvidence(response) || (response.charts || []).length > 0) {
    return "EDA exploration — no entity risk explanation (by design).";
  }
  if (route === "feature_only" || route === "simple_lookup" || intent === "threshold_aggregation") {
    return "Informational query — no risk explanation generated (expected for SQL/feature-only paths).";
  }
  return "No compliance explanation tool result.";
}

export function extractExplanation(response: FinalResponse): ExplanationView | null {
  const tools = response.supporting_evidence || [];
  for (let i = tools.length - 1; i >= 0; i -= 1) {
    const tool = tools[i];
    if (tool.tool !== "explanation" || tool.status !== "success") continue;
    const data = tool.data || {};
    const flagged = response.results.find((r) => r.result_type === "flagged") as
      | FlaggedResult
      | undefined;
    return {
      summary: String(data.summary || ""),
      reasons: Array.isArray(data.reasons) ? data.reasons.map(String) : [],
      riskLevel: String(data.risk_level || flagged?.risk_level || "—").toUpperCase(),
      riskScore:
        typeof data.risk_score === "number" ? data.risk_score : flagged?.risk_score ?? null,
      confidence:
        typeof data.confidence === "number" ? data.confidence : flagged?.confidence ?? null,
      escalationAction: String(
        data.escalation_action || flagged?.escalation_action || "—",
      ).toUpperCase(),
      recommendedAction: String(
        data.recommended_action_explanation || data.recommended_action || "",
      ),
      evidenceIds: Array.isArray(data.evidence_ids) ? data.evidence_ids.map(String) : [],
      source: String(data.source || "template"),
      riskLevelExplanation: String(data.risk_level_explanation || ""),
    };
  }
  return null;
}

export function flaggedResults(response: FinalResponse): FlaggedResult[] {
  return response.results.filter((r): r is FlaggedResult => r.result_type === "flagged");
}

export function statusBanner(response: FinalResponse): {
  kind: "ok" | "soft_partial" | "hard_partial" | "failed" | "info";
  message: string;
} {
  const status = response.status || "completed";
  const skipped = response.execution_summary?.tools_skipped || [];
  const onlyOptional =
    skipped.length > 0 &&
    skipped.every(
      (s) =>
        OPTIONAL_SKIP_TOOLS.has(s.tool) ||
        /optional|NODE_TIMEOUT|DEPENDENCY_SKIPPED/i.test(s.reason || ""),
    );

  if (status === "failed") {
    return { kind: "failed", message: "Investigation failed — see Execution Summary." };
  }
  if (status === "partial" && onlyOptional) {
    return {
      kind: "soft_partial",
      message:
        "Completed with optional tool(s) skipped — core findings below. See Execution Summary.",
    };
  }
  if (status === "partial") {
    return {
      kind: "hard_partial",
      message: "Partial result — some tools failed or were skipped. See Execution Summary.",
    };
  }
  return { kind: "ok", message: "Investigation completed." };
}

export function explanationSourceBanner(response: FinalResponse): string | null {
  const expl = extractExplanation(response);
  const fallbacks = response.execution_summary?.fallbacks || [];
  if (expl?.source === "ollama") return "Explanation source: Ollama (grounded LLM)";
  if (expl?.source === "template_fallback" || /LLM unavailable|template/i.test(fallbacks.join(" "))) {
    return "Explanation source: deterministic template (LLM unavailable or timed out)";
  }
  if (expl?.source === "template") return "Explanation source: deterministic template";
  return null;
}

export function keyFieldsFromTool(tool: ToolResult): Array<{ label: string; value: string }> {
  const out: Array<{ label: string; value: string }> = [];
  const data = tool.data || {};
  if (tool.tool === "sql_lookup" && tool.operation === "count_by_customer") {
    out.push({ label: "matching_customers", value: String(data.total_matching ?? "—") });
    out.push({ label: "minimum_count", value: String(data.minimum_count ?? "—") });
    return out;
  }
  if (tool.tool === "sql_lookup" && typeof data.count === "number") {
    out.push({ label: "count", value: String(data.count) });
  }
  if (tool.tool === "anomaly_detection" && Array.isArray(data.rules)) {
    for (const rule of data.rules.slice(0, 5)) {
      if (!rule || typeof rule !== "object") continue;
      const r = rule as Record<string, unknown>;
      out.push({
        label: String(r.rule_id || "rule"),
        value: `fired=${r.fired} severity=${r.severity || "—"} code=${r.reason_code || "—"}`,
      });
    }
  }
  if (tool.tool === "feature_engineering") {
    const fr = (data.feature_result || data) as Record<string, unknown>;
    const parsed = parseFeatureValues(fr);
    for (const item of parsed.slice(0, 8)) {
      out.push({ label: item.name, value: item.value });
    }
    if (typeof data.window_role === "string") {
      out.push({ label: "window", value: data.window_role });
    }
  }
  if (tool.tool === "risk_classification") {
    for (const key of ["risk_level", "risk_score", "confidence", "entity_id"]) {
      if (data[key] !== undefined) out.push({ label: key, value: String(data[key]) });
    }
  }
  if (tool.tool === "escalation") {
    for (const key of ["escalation_action", "alert_id", "alert_created", "risk_level"]) {
      if (data[key] !== undefined) out.push({ label: key, value: String(data[key]) });
    }
  }
  if (tool.tool === "explanation" && data.source) {
    out.push({ label: "source", value: String(data.source) });
  }
  if (tool.tool === "eda" && typeof data.transaction_count === "number") {
    out.push({ label: "transaction_count", value: String(data.transaction_count) });
    if (typeof data.customer_count === "number") {
      out.push({ label: "customer_count", value: String(data.customer_count) });
    }
  }
  if (out.length === 0 && Object.keys(data).length) {
    out.push({ label: "keys", value: Object.keys(data).slice(0, 12).join(", ") });
  }
  return out;
}

export function buildInvestigationPack(args: {
  response: FinalResponse;
  demoAsOf?: string;
  alertId?: string | null;
}): Record<string, unknown> {
  const { response, demoAsOf = DEMO_AS_OF, alertId } = args;
  const explanation = extractExplanation(response);
  return {
    pack_version: "investigation_pack.v1",
    generated_at: new Date().toISOString(),
    as_of: demoAsOf,
    request_id: response.request_id,
    query: response.execution_summary.query,
    intent: response.execution_summary.detected_intent,
    route: response.execution_summary.route,
    filters: response.execution_summary.filters,
    execution_summary: response.execution_summary,
    status: response.status,
    results: response.results,
    supporting_evidence: response.supporting_evidence,
    charts: response.charts,
    explanation: explanation,
    answer: response.answer,
    alert_id: alertId || null,
  };
}

export function buildAlertCasePack(args: {
  response: FinalResponse;
  flagged: FlaggedResult;
  query: string;
}): Record<string, unknown> {
  const explanation = extractExplanation(args.response);
  const flagged = args.flagged;
  const normalizedExplanation = {
    summary: explanation?.summary || flagged.reasons.join("; ") || "Flagged finding from investigation",
    reasons: explanation?.reasons?.length ? explanation.reasons : flagged.reasons,
    riskLevel: explanation?.riskLevel || flagged.risk_level,
    riskScore: explanation?.riskScore ?? flagged.risk_score,
    confidence: explanation?.confidence ?? flagged.confidence,
    escalationAction: explanation?.escalationAction || flagged.escalation_action,
    recommendedAction: explanation?.recommendedAction || "",
    evidenceIds: explanation?.evidenceIds?.length
      ? explanation.evidenceIds
      : flagged.evidence_refs || [],
    source: explanation?.source || "investigation",
    riskLevelExplanation: explanation?.riskLevelExplanation || "",
  };
  return {
    pack_version: "alert_case_pack.v1",
    request_id: args.response.request_id,
    query: args.query,
    as_of: DEMO_AS_OF,
    flagged_result: flagged,
    explanation: normalizedExplanation,
    supporting_evidence: args.response.supporting_evidence || [],
    execution_summary: {
      intent: args.response.execution_summary.detected_intent,
      route: args.response.execution_summary.route,
      tools_invoked: args.response.execution_summary.tools_invoked,
      tools_skipped: args.response.execution_summary.tools_skipped,
    },
  };
}
