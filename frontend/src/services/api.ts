export enum IntentType {
  BROAD_EXPLORATION = "broad_exploration",
  SIMPLE_LOOKUP = "simple_lookup",
  THRESHOLD_AGGREGATION = "threshold_aggregation",
  FEATURE_COMPARISON = "feature_comparison",
  PATTERN_SEARCH = "pattern_search",
  ENTITY_INVESTIGATION = "entity_investigation",
  TRANSACTION_SCORING = "transaction_scoring",
  EXPLANATION_REQUEST = "explanation_request"
}

export enum RouteType {
  SIMPLE_LOOKUP = "simple_lookup",
  FEATURE_ONLY = "feature_only",
  FULL_INVESTIGATION = "full_investigation"
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
  EXPLANATION = "explanation"
}

export enum ToolStatus {
  SUCCESS = "success",
  PARTIAL = "partial",
  SKIPPED = "skipped",
  FAILED = "failed"
}

export enum EntityType {
  CUSTOMER = "customer",
  ACCOUNT = "account",
  TRANSACTION = "transaction"
}

export enum RiskLevel {
  LOW = "LOW",
  MEDIUM = "MEDIUM",
  HIGH = "HIGH"
}

export enum EscalationAction {
  MONITOR = "monitor",
  REVIEW = "review",
  REPORT = "report"
}

export enum ChartType {
  BAR = "bar",
  LINE = "line",
  HISTOGRAM = "histogram",
  SCATTER = "scatter",
  TABLE = "table"
}

// Frontend API type definitions matching backend contract-v1
export interface SkippedTool {
  tool: string;
  reason: string;
}

export interface ExecutionSummary {
  query: string;
  detected_intent: string;
  route: string;
  filters: Record<string, any>;
  plan?: {
    strategy: string;
    planner_version: string;
    steps: Array<{
      step_id: string;
      tool: string;
      operation: string;
      parameters: Record<string, any>;
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
  result_type: 'informational';
  entity_type: string | null;
  entity_id: string | null;
  summary: string;
  data: Record<string, any>;
  evidence_refs: string[];
}

export interface FlaggedResult {
  result_type: 'flagged';
  entity_type: string;
  entity_id: string;
  risk_score: number;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  confidence: number;
  reasons: string[];
  escalation_action: 'monitor' | 'review' | 'report';
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
  scope: Record<string, any>;
  data: Record<string, any>;
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
  error?: {
    code: string;
    message: string;
    retryable: boolean;
  } | null;
}

export interface ChartSpec {
  chart_id: string;
  chart_type: 'bar' | 'line' | 'histogram' | 'scatter' | 'table';
  title: string;
  data: {
    labels: string[];
    values: number[];
  };
  x_label?: string | null;
  y_label?: string | null;
  evidence_refs: string[];
}

export interface FinalResponse {
  contract_version: 'v1';
  request_id: string;
  generated_at: string;
  execution_summary: ExecutionSummary;
  results: ResultItem[];
  supporting_evidence: ToolResult[];
  charts: ChartSpec[];
  answer: string;
}

export interface AuditLog {
  timestamp: string;
  reviewer: string;
  transition: string;
  reason?: string;
}

export interface Alert {
  id: string;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  entity_type: 'customer' | 'transaction' | 'account';
  entity_id: string;
  opened_at: string;
  status: 'open' | 'in_review' | 'escalated' | 'dismissed' | 'closed';
  age_description: string;
  results: ResultItem[];
  supporting_evidence: ToolResult[];
  audit_history: AuditLog[];
}

export interface CustomerProfile {
  id: string;
  name: string;
  country: string;
  segment: string;
  status: 'active' | 'suspended' | 'frozen';
  created_at: string;
  risk_rating: 'LOW' | 'MEDIUM' | 'HIGH';
  kyc_occupation: string;
  kyc_income_usd: string;
  kyc_risk_score: number;
  recent_transactions: Array<{
    id: string;
    amount: number;
    currency: string;
    date: string;
    status: string;
  }>;
  alerts: Array<{
    id: string;
    status: string;
    date: string;
  }>;
}

// 6 MANDATORY QUERY DATA FIXTURES
const QUERY_RESPONSES: Record<number, FinalResponse> = {
  1: {
    contract_version: 'v1',
    request_id: 'req-structuring-101',
    generated_at: '2026-07-25T17:02:40Z',
    execution_summary: {
      query: 'Find structuring patterns in the last 30 days',
      detected_intent: 'pattern_search' as IntentType,
      route: 'full_investigation' as RouteType,
      filters: {
        date_from: '2026-06-25T00:00:00Z',
        date_to: '2026-07-25T23:59:59Z',
        pattern_type: 'structuring',
        currency: 'USD',
        max_results: 100
      },
      plan: {
        strategy: 'targeted_pattern_search',
        planner_version: 'template.v1',
        steps: [
          {
            step_id: 'features',
            tool: 'feature_engineering',
            operation: 'structuring_features',
            parameters: { window_days: 30 },
            reason: 'Compute transaction counts and values relative to the reporting threshold.'
          },
          {
            step_id: 'rules',
            tool: 'anomaly_detection',
            operation: 'rules_only',
            parameters: {},
            depends_on: ['features'],
            reason: 'Evaluate deterministic structuring threshold rules against feature outputs.'
          }
        ]
      },
      tools_invoked: ['feature_engineering' as ToolName, 'anomaly_detection' as ToolName],
      tools_skipped: [
        { tool: 'eda', reason: 'full profiling not required for a targeted pattern query' },
        { tool: 'sql_lookup', reason: 'feature engineering covers threshold logic, direct lookup skipped' }
      ],
      fallbacks: [],
      warnings: []
    },
    results: [
      {
        result_type: 'flagged',
        entity_type: 'customer',
        entity_id: 'C-4521',
        risk_score: 78,
        risk_level: 'HIGH',
        confidence: 0.88,
        reasons: ['structuring.v1', 'profile_deviation.v1'],
        escalation_action: 'report',
        evidence_refs: ['ev.features.1', 'ev.rules.1']
      },
      {
        result_type: 'flagged',
        entity_type: 'transaction',
        entity_id: 'T-88213',
        risk_score: 52,
        risk_level: 'MEDIUM',
        confidence: 0.75,
        reasons: ['velocity.v1'],
        escalation_action: 'review',
        evidence_refs: ['ev.features.2']
      }
    ],
    supporting_evidence: [
      {
        tool: 'feature_engineering' as ToolName,
        operation: 'structuring_features',
        status: 'success',
        scope: { date_from: '2026-06-25T00:00:00Z', date_to: '2026-07-25T23:59:59Z' },
        data: {
          rolling_count: 12,
          average_amount: 9850,
          cash_in_ratio: 0.95,
          days_active: 8
        },
        evidence: [
          {
            evidence_id: 'ev.features.1',
            tool: 'feature_engineering',
            kind: 'feature',
            json_path: '$.rolling_count',
            label: 'Rolling transaction count (30 days)'
          }
        ],
        warnings: [],
        duration_ms: 124,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'features_engine.v1', query_or_version: 'v1.0.4' }
      },
      {
        tool: 'anomaly_detection' as ToolName,
        operation: 'rules_only',
        status: 'success',
        scope: { date_from: '2026-06-25T00:00:00Z', date_to: '2026-07-25T23:59:59Z' },
        data: {
          rules_fired: ['structuring.v1', 'profile_deviation.v1'],
          threshold_exceeded: true,
          limit_applied: 10000
        },
        evidence: [
          {
            evidence_id: 'ev.rules.1',
            tool: 'anomaly_detection',
            kind: 'rule',
            json_path: '$.rules_fired',
            label: 'Fired AML rules: structuring.v1, profile_deviation.v1'
          }
        ],
        warnings: [],
        duration_ms: 45,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'anomaly_detector_rules.v1', query_or_version: 'policy.v1' }
      },
      {
        tool: 'feature_engineering' as ToolName,
        operation: 'velocity_features',
        status: 'success',
        scope: { date_from: '2026-06-25T00:00:00Z', date_to: '2026-07-25T23:59:59Z' },
        data: {
          velocity_index: 3.2,
          historical_daily_avg: 1.1,
          deviation_factor: 2.9
        },
        evidence: [
          {
            evidence_id: 'ev.features.2',
            tool: 'feature_engineering',
            kind: 'feature',
            json_path: '$.velocity_index',
            label: 'Velocity index (30 days)'
          }
        ],
        warnings: [],
        duration_ms: 82,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'features_engine.v1', query_or_version: 'v1.0.4' }
      }
    ],
    charts: [
      {
        chart_id: 'structuring-daily-volume',
        chart_type: 'bar' as ChartType,
        title: 'Daily transaction count under $10,000 threshold (last 30 days)',
        data: {
          labels: ['06-25', '06-28', '07-01', '07-04', '07-07', '07-10', '07-13', '07-16', '07-19', '07-22', '07-25'],
          values: [1, 2, 0, 1, 3, 2, 4, 1, 2, 3, 2]
        },
        x_label: 'Day',
        y_label: 'Transactions',
        evidence_refs: ['ev.features.1']
      }
    ],
    answer: 'Analysis of transaction volume and cash flows over the last 30 days identified potential structuring patterns. Two entities were flagged: Customer C-4521 is classified as HIGH risk (score 78) based on 12 deposits structured just below the $10,000 threshold (average deposit of $9,850). Transaction T-88213 is classified as MEDIUM risk (score 52) due to an elevated velocity index (3.2 vs. 1.1 historical baseline).'
  },
  2: {
    contract_version: 'v1',
    request_id: 'req-lookup-202',
    generated_at: '2026-07-25T17:02:40Z',
    execution_summary: {
      query: 'Which customers made 10+ transactions under $10,000?',
      detected_intent: 'threshold_aggregation' as IntentType,
      route: 'simple_lookup' as RouteType,
      filters: {
        amount_max: 10000,
        count_min: 10,
        max_results: 100
      },
      plan: null,
      tools_invoked: ['sql_lookup' as ToolName],
      tools_skipped: [
        { tool: 'eda', reason: 'direct threshold aggregation does not require broad exploratory profiling' },
        { tool: 'feature_engineering', reason: 'sql aggregation covers query requirement; complex feature calculations skipped' },
        { tool: 'anomaly_detection', reason: 'query requested lookup, not risk scoring or anomaly profiling' }
      ],
      fallbacks: [],
      warnings: []
    },
    results: [
      {
        result_type: 'informational',
        entity_type: 'customer',
        entity_id: 'C-4521',
        summary: 'Customer C-4521 made 12 transactions under $10,000 totaling $95,400',
        data: {
          count: 12,
          total_amount: 95400,
          currency: 'USD'
        },
        evidence_refs: ['ev.sql.1']
      },
      {
        result_type: 'informational',
        entity_type: 'customer',
        entity_id: 'C-9082',
        summary: 'Customer C-9082 made 10 transactions under $10,000 totaling $82,100',
        data: {
          count: 10,
          total_amount: 82100,
          currency: 'USD'
        },
        evidence_refs: ['ev.sql.1']
      }
    ],
    supporting_evidence: [
      {
        tool: 'sql_lookup' as ToolName,
        operation: 'threshold_aggregation',
        status: 'success',
        scope: { amount_max: 10000, count_min: 10 },
        data: {
          matches: [
            { customer_id: 'C-4521', count: 12, total_amount: 95400 },
            { customer_id: 'C-9082', count: 10, total_amount: 82100 }
          ],
          query_executed: 'SELECT customer_id, COUNT(*), SUM(amount) FROM transactions WHERE amount < 10000 GROUP BY customer_id HAVING COUNT(*) >= 10'
        },
        evidence: [
          {
            evidence_id: 'ev.sql.1',
            tool: 'sql_lookup',
            kind: 'records',
            json_path: '$.matches',
            label: 'SQL Query output records for count >= 10 and amount < 10000'
          }
        ],
        warnings: [],
        duration_ms: 18,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'sqlite_db.v1', query_or_version: 'v1.0.0' }
      }
    ],
    charts: [
      {
        chart_id: 'customer-counts',
        chart_type: 'bar' as ChartType,
        title: 'Transaction counts under $10,000 per customer',
        data: {
          labels: ['C-4521', 'C-9082'],
          values: [12, 10]
        },
        x_label: 'Customer ID',
        y_label: 'Transaction Count',
        evidence_refs: ['ev.sql.1']
      }
    ],
    answer: 'Executed SQL threshold aggregation directly. Found 2 customers who made 10 or more transactions under $10,000. Customer C-4521 (12 transactions, totaling $95,400) and Customer C-9082 (10 transactions, totaling $82,100).'
  },
  3: {
    contract_version: 'v1',
    request_id: 'req-entity-303',
    generated_at: '2026-07-25T17:02:40Z',
    execution_summary: {
      query: 'Is customer ID 4521 suspicious?',
      detected_intent: 'entity_investigation' as IntentType,
      route: 'full_investigation' as RouteType,
      filters: {
        customer_ids: ['C-4521'],
        max_results: 100
      },
      plan: {
        strategy: 'entity_investigation_plan',
        planner_version: 'template.v1',
        steps: [
          {
            step_id: 'sql_profile',
            tool: 'sql_lookup',
            operation: 'entity_lookup',
            parameters: { customer_id: 'C-4521' },
            reason: 'Retrieve core customer profile and recent transactions.'
          },
          {
            step_id: 'features',
            tool: 'feature_engineering',
            operation: 'profile_features',
            depends_on: ['sql_profile'],
            parameters: { customer_id: 'C-4521' },
            reason: 'Calculate KYC profiling deviations and volume metrics.'
          },
          {
            step_id: 'anomalies',
            tool: 'anomaly_detection',
            operation: 'hybrid_scorer',
            depends_on: ['features'],
            parameters: { customer_id: 'C-4521' },
            reason: 'Evaluate rules and supervised ML scoring.'
          }
        ]
      },
      tools_invoked: ['sql_lookup' as ToolName, 'feature_engineering' as ToolName, 'anomaly_detection' as ToolName],
      tools_skipped: [
        { tool: 'eda', reason: 'individual customer lookup skips dataset-wide exploratory data profiling' }
      ],
      fallbacks: [],
      warnings: []
    },
    results: [
      {
        result_type: 'flagged',
        entity_type: 'customer',
        entity_id: 'C-4521',
        risk_score: 85,
        risk_level: 'HIGH',
        confidence: 0.92,
        reasons: ['structuring.v1', 'profile_deviation.v1'],
        escalation_action: 'report',
        evidence_refs: ['ev.sql.cust', 'ev.features.cust', 'ev.rules.cust']
      }
    ],
    supporting_evidence: [
      {
        tool: 'sql_lookup' as ToolName,
        operation: 'entity_lookup',
        status: 'success',
        scope: { customer_ids: ['C-4521'] },
        data: {
          customer_details: {
            id: 'C-4521',
            name: 'Alpha Services LLC',
            country: 'IN',
            occupation: 'Corporate Trading',
            risk_tier_db: 'HIGH',
            created_at: '2026-01-10T12:00:00Z'
          }
        },
        evidence: [
          {
            evidence_id: 'ev.sql.cust',
            tool: 'sql_lookup',
            kind: 'profile',
            json_path: '$.customer_details',
            label: 'Customer Profile database record'
          }
        ],
        warnings: [],
        duration_ms: 15,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'sqlite_db.v1', query_or_version: 'v1.0.0' }
      },
      {
        tool: 'feature_engineering' as ToolName,
        operation: 'profile_features',
        status: 'success',
        scope: { customer_ids: ['C-4521'] },
        data: {
          rolling_30d_amount: 114000,
          kyc_monthly_income_usd: 12000,
          income_multiplier: 9.5,
          occupation_deviation_score: 0.78
        },
        evidence: [
          {
            evidence_id: 'ev.features.cust',
            tool: 'feature_engineering',
            kind: 'feature',
            json_path: '$.occupation_deviation_score',
            label: 'KYC profile deviation score'
          }
        ],
        warnings: [],
        duration_ms: 92,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'features_engine.v1', query_or_version: 'v1.0.4' }
      },
      {
        tool: 'anomaly_detection' as ToolName,
        operation: 'hybrid_scorer',
        status: 'success',
        scope: { customer_ids: ['C-4521'] },
        data: {
          structuring_signal: 0.88,
          ml_score: 82.5,
          ml_threshold: 50.0,
          rules_triggered: ['structuring.v1', 'profile_deviation.v1']
        },
        evidence: [
          {
            evidence_id: 'ev.rules.cust',
            tool: 'anomaly_detection',
            kind: 'ml_score',
            json_path: '$.ml_score',
            label: 'Supervised ULB fraud scorer ranking'
          }
        ],
        warnings: [],
        duration_ms: 61,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'anomaly_detector_hybrid.v1', query_or_version: 'policy.v1' }
      }
    ],
    charts: [
      {
        chart_id: 'customer-risk-profile',
        chart_type: 'bar' as ChartType,
        title: 'Risk Indicators vs Baseline Thresholds',
        data: {
          labels: ['Structuring Signal', 'Profile Deviation', 'ML Scorer', 'KYC Multiplier'],
          values: [88, 78, 83, 95]
        },
        x_label: 'Risk Dimension',
        y_label: 'Score %',
        evidence_refs: ['ev.features.cust', 'ev.rules.cust']
      }
    ],
    answer: 'Customer C-4521 is classified as HIGH risk (score 85). The investigation verifies a sequence of 12 rapid cash deposits under the $10,000 threshold (structuring signature) and a massive 9.5x deviation from their declared KYC monthly income baseline. The supervised ML fraud ranking scorer returned a high probability rank of 82.5. Immediate escalation and reporting is recommended.'
  },
  4: {
    contract_version: 'v1',
    request_id: 'req-spending-404',
    generated_at: '2026-07-25T17:02:40Z',
    execution_summary: {
      query: 'Did customer 123 suddenly increase spending this month?',
      detected_intent: 'feature_comparison' as IntentType,
      route: 'feature_only' as RouteType,
      filters: {
        customer_ids: ['C-0123'],
        max_results: 100
      },
      plan: null,
      tools_invoked: ['sql_lookup' as ToolName, 'feature_engineering' as ToolName],
      tools_skipped: [
        { tool: 'eda', reason: 'dataset-wide profiling skipped for individual customer request' },
        { tool: 'anomaly_detection', reason: 'query requested spending increase features, not risk classification or rules-based anomaly flagging' }
      ],
      fallbacks: [],
      warnings: []
    },
    results: [
      {
        result_type: 'informational',
        entity_type: 'customer',
        entity_id: 'C-0123',
        summary: 'Customer C-0123 monthly spend increased from $4,200 baseline to $10,164 (142% increase)',
        data: {
          baseline_monthly_average: 4200,
          current_month_spend: 10164,
          increase_percentage: 142,
          deviation_zscore: 2.85
        },
        evidence_refs: ['ev.features.123']
      }
    ],
    supporting_evidence: [
      {
        tool: 'feature_engineering' as ToolName,
        operation: 'spending_deviation',
        status: 'success',
        scope: { customer_ids: ['C-0123'] },
        data: {
          baseline_monthly_average: 4200,
          current_month_spend: 10164,
          increase_ratio: 2.42,
          deviation_zscore: 2.85
        },
        evidence: [
          {
            evidence_id: 'ev.features.123',
            tool: 'feature_engineering',
            kind: 'feature',
            json_path: '$.current_month_spend',
            label: 'Current month spend vs historical baseline'
          }
        ],
        warnings: [],
        duration_ms: 48,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'features_engine.v1', query_or_version: 'v1.0.4' }
      }
    ],
    charts: [
      {
        chart_id: 'spend-trend',
        chart_type: 'line' as ChartType,
        title: 'Customer C-0123 Monthly Spend Trend (USD)',
        data: {
          labels: ['Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul (Current)'],
          values: [4100, 4300, 3950, 4250, 4200, 10164]
        },
        x_label: 'Month',
        y_label: 'Spend ($)',
        evidence_refs: ['ev.features.123']
      }
    ],
    answer: 'Executed feature engineering baseline-deviation calculations. Customer C-0123 spending increased by 142% this month. Current month spend is $10,164 compared to a historical monthly average of $4,200 (Z-score: 2.85, representing a significant statistical spike).'
  },
  5: {
    contract_version: 'v1',
    request_id: 'req-filter-505',
    generated_at: '2026-07-25T17:02:40Z',
    execution_summary: {
      query: 'Show me transactions over $10,000',
      detected_intent: 'simple_lookup' as IntentType,
      route: 'simple_lookup' as RouteType,
      filters: {
        amount_min: 10000,
        max_results: 100
      },
      plan: null,
      tools_invoked: ['sql_lookup' as ToolName],
      tools_skipped: [
        { tool: 'eda', reason: 'a direct amount filter does not require dataset profiling' },
        { tool: 'feature_engineering', reason: 'features are not required for simple lookup queries' },
        { tool: 'anomaly_detection', reason: 'anomaly detection bypassed for simple lookup queries' }
      ],
      fallbacks: [],
      warnings: []
    },
    results: [
      {
        result_type: 'informational',
        entity_type: 'transaction',
        entity_id: 'T-90812',
        summary: 'Transaction T-90812 for $15,400.00',
        data: {
          amount: 15400,
          currency: 'USD',
          date: '2026-07-20T14:22:00Z',
          customer_id: 'C-4521'
        },
        evidence_refs: ['ev.sql.over10k']
      },
      {
        result_type: 'informational',
        entity_type: 'transaction',
        entity_id: 'T-90815',
        summary: 'Transaction T-90815 for $12,000.00',
        data: {
          amount: 12000,
          currency: 'USD',
          date: '2026-07-22T09:15:00Z',
          customer_id: 'C-9082'
        },
        evidence_refs: ['ev.sql.over10k']
      }
    ],
    supporting_evidence: [
      {
        tool: 'sql_lookup' as ToolName,
        operation: 'amount_filter',
        status: 'success',
        scope: { amount_min: 10000 },
        data: {
          records: [
            { transaction_id: 'T-90812', amount: 15400, currency: 'USD', date: '2026-07-20T14:22:00Z', customer_id: 'C-4521' },
            { transaction_id: 'T-90815', amount: 12000, currency: 'USD', date: '2026-07-22T09:15:00Z', customer_id: 'C-9082' }
          ],
          query_executed: 'SELECT * FROM transactions WHERE amount > 10000 ORDER BY date DESC LIMIT 100'
        },
        evidence: [
          {
            evidence_id: 'ev.sql.over10k',
            tool: 'sql_lookup',
            kind: 'records',
            json_path: '$.records',
            label: 'SQL filter for transactions > 10000'
          }
        ],
        warnings: [],
        duration_ms: 12,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'sqlite_db.v1', query_or_version: 'v1.0.0' }
      }
    ],
    charts: [],
    answer: 'Executed SQL direct lookup. Found 2 transactions over $10,000: T-90812 ($15,400.00) and T-90815 ($12,000.00).'
  },
  6: {
    contract_version: 'v1',
    request_id: 'req-eda-606',
    generated_at: '2026-07-25T17:02:40Z',
    execution_summary: {
      query: 'Analyse this dataset for suspicious activity',
      detected_intent: 'broad_exploration' as IntentType,
      route: 'full_investigation' as RouteType,
      filters: {
        max_results: 100
      },
      plan: {
        strategy: 'broad_dataset_exploration',
        planner_version: 'template.v1',
        steps: [
          {
            step_id: 'eda_profile',
            tool: 'eda',
            operation: 'dataset_profile',
            parameters: {},
            reason: 'Profile total volumes, missingness, and general distributions.'
          },
          {
            step_id: 'feature_sweep',
            tool: 'feature_engineering',
            operation: 'bulk_aml_features',
            depends_on: ['eda_profile'],
            parameters: {},
            reason: 'Calculate bulk velocity and structuring flags for all active customers.'
          },
          {
            step_id: 'anomaly_sweep',
            tool: 'anomaly_detection',
            operation: 'rules_and_ml_sweep',
            depends_on: ['feature_sweep'],
            parameters: {},
            reason: 'Execute rules engine and ML scorer across the populated cohorts.'
          }
        ]
      },
      tools_invoked: ['eda' as ToolName, 'feature_engineering' as ToolName, 'anomaly_detection' as ToolName],
      tools_skipped: [],
      fallbacks: [],
      warnings: []
    },
    results: [
      {
        result_type: 'flagged',
        entity_type: 'customer',
        entity_id: 'C-4521',
        risk_score: 78,
        risk_level: 'HIGH',
        confidence: 0.88,
        reasons: ['structuring.v1'],
        escalation_action: 'report',
        evidence_refs: ['ev.eda.all', 'ev.rules.all']
      },
      {
        result_type: 'flagged',
        entity_type: 'customer',
        entity_id: 'C-9082',
        risk_score: 55,
        risk_level: 'MEDIUM',
        confidence: 0.82,
        reasons: ['velocity.v1'],
        escalation_action: 'review',
        evidence_refs: ['ev.eda.all']
      }
    ],
    supporting_evidence: [
      {
        tool: 'eda' as ToolName,
        operation: 'dataset_profile',
        status: 'success',
        scope: {},
        data: {
          total_transactions: 284807,
          unique_customers: 500,
          amount_min: 0.1,
          amount_max: 25000,
          missing_values: 0,
          labeled_fraud_records: 492
        },
        evidence: [
          {
            evidence_id: 'ev.eda.all',
            tool: 'eda',
            kind: 'profiling',
            json_path: '$.total_transactions',
            label: 'EDA general dataset profiling'
          }
        ],
        warnings: [],
        duration_ms: 1240,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'eda_engine.v1', query_or_version: 'v1.0.0' }
      },
      {
        tool: 'anomaly_detection' as ToolName,
        operation: 'rules_and_ml_sweep',
        status: 'success',
        scope: {},
        data: {
          total_flagged_entities: 2,
          total_scans: 500,
          rules_scans_completed: true,
          ml_scans_completed: true
        },
        evidence: [
          {
            evidence_id: 'ev.rules.all',
            tool: 'anomaly_detection',
            kind: 'rules',
            json_path: '$.total_flagged_entities',
            label: 'Broad anomaly rules sweep'
          }
        ],
        warnings: [],
        duration_ms: 382,
        produced_at: '2026-07-25T17:02:40Z',
        provenance: { source: 'anomaly_detector_bulk.v1', query_or_version: 'policy.v1' }
      }
    ],
    charts: [
      {
        chart_id: 'dataset-risk-distribution',
        chart_type: 'bar' as ChartType,
        title: 'Risk Score Distribution (Overall Cohort)',
        data: {
          labels: ['0-20 (Low)', '21-40 (Low)', '41-60 (Med)', '61-80 (Med)', '81-100 (High)'],
          values: [420, 62, 12, 4, 2]
        },
        x_label: 'Risk Score Range',
        y_label: 'Number of Customers',
        evidence_refs: ['ev.eda.all']
      }
    ],
    answer: 'Executed broad dataset exploration. Profiling run complete on 284,807 transactions. Identified two high-scoring anomalies: Customer C-4521 (High risk, score 78) showing structuring signatures, and Customer C-9082 (Medium risk, score 55) showing velocity spikes. Full EDA profiling and anomaly sweep metadata are detailed below.'
  }
};

// INITIAL ALERTS DATABASE
const INITIAL_ALERTS: Alert[] = [
  {
    id: 'A-101',
    risk_level: 'HIGH',
    entity_type: 'customer',
    entity_id: 'C-4521',
    opened_at: '2026-07-25T15:02:00Z',
    status: 'open',
    age_description: '2h ago',
    results: [QUERY_RESPONSES[3].results[0]],
    supporting_evidence: QUERY_RESPONSES[3].supporting_evidence,
    audit_history: [
      { timestamp: '2026-07-25T15:02:00Z', reviewer: 'system', transition: 'open' }
    ]
  },
  {
    id: 'A-102',
    risk_level: 'MEDIUM',
    entity_type: 'transaction',
    entity_id: 'T-88213',
    opened_at: '2026-07-25T13:00:00Z',
    status: 'in_review',
    age_description: '4h ago',
    results: [QUERY_RESPONSES[1].results[1]],
    supporting_evidence: [QUERY_RESPONSES[1].supporting_evidence[2]],
    audit_history: [
      { timestamp: '2026-07-25T13:00:00Z', reviewer: 'system', transition: 'open' },
      { timestamp: '2026-07-25T13:10:00Z', reviewer: 'reviewer_1', transition: 'open -> in_review' }
    ]
  },
  {
    id: 'A-103',
    risk_level: 'LOW',
    entity_type: 'customer',
    entity_id: 'C-0123',
    opened_at: '2026-07-24T10:00:00Z',
    status: 'closed',
    age_description: '1d ago',
    results: [QUERY_RESPONSES[4].results[0] as any],
    supporting_evidence: QUERY_RESPONSES[4].supporting_evidence,
    audit_history: [
      { timestamp: '2026-07-24T10:00:00Z', reviewer: 'system', transition: 'open' },
      { timestamp: '2026-07-24T14:30:00Z', reviewer: 'reviewer_1', transition: 'open -> in_review' },
      { timestamp: '2026-07-24T15:00:00Z', reviewer: 'reviewer_1', transition: 'in_review -> dismissed', reason: 'Normal seasonal shopping fluctuation.' },
      { timestamp: '2026-07-24T15:01:00Z', reviewer: 'reviewer_1', transition: 'dismissed -> closed' }
    ]
  }
];

// CUSTOMER DETAILS DATABASE
const CUSTOMERS_DB: Record<string, CustomerProfile> = {
  'C-4521': {
    id: 'C-4521',
    name: 'Alpha Services LLC',
    country: 'IN',
    segment: 'Corporate',
    status: 'active',
    created_at: '2026-01-10T12:00:00Z',
    risk_rating: 'HIGH',
    kyc_occupation: 'Corporate Trading',
    kyc_income_usd: '12,000 / mo',
    kyc_risk_score: 85,
    recent_transactions: [
      { id: 'TX-90812', amount: 9850, currency: 'USD', date: '2026-07-25T14:22:00Z', status: 'completed' },
      { id: 'TX-90811', amount: 9900, currency: 'USD', date: '2026-07-25T10:15:00Z', status: 'completed' },
      { id: 'TX-90810', amount: 9800, currency: 'USD', date: '2026-07-24T16:40:00Z', status: 'completed' },
      { id: 'TX-90809', amount: 9950, currency: 'USD', date: '2026-07-24T11:05:00Z', status: 'completed' },
      { id: 'TX-90808', amount: 9750, currency: 'USD', date: '2026-07-23T15:20:00Z', status: 'completed' }
    ],
    alerts: [
      { id: 'A-101', status: 'open', date: '2026-07-25' }
    ]
  },
  'C-9082': {
    id: 'C-9082',
    name: 'Beta Trade Solutions',
    country: 'US',
    segment: 'Corporate',
    status: 'active',
    created_at: '2026-03-15T09:30:00Z',
    risk_rating: 'MEDIUM',
    kyc_occupation: 'Import Export',
    kyc_income_usd: '45,000 / mo',
    kyc_risk_score: 55,
    recent_transactions: [
      { id: 'TX-80123', amount: 8200, currency: 'USD', date: '2026-07-24T11:20:00Z', status: 'completed' },
      { id: 'TX-80122', amount: 7900, currency: 'USD', date: '2026-07-23T10:10:00Z', status: 'completed' },
      { id: 'TX-80121', amount: 8150, currency: 'USD', date: '2026-07-22T09:15:00Z', status: 'completed' }
    ],
    alerts: [
      { id: 'A-102', status: 'in_review', date: '2026-07-25' }
    ]
  },
  'C-0123': {
    id: 'C-0123',
    name: 'Sarah Jenkins',
    country: 'UK',
    segment: 'Retail',
    status: 'active',
    created_at: '2025-11-01T08:00:00Z',
    risk_rating: 'LOW',
    kyc_occupation: 'Software Engineer',
    kyc_income_usd: '8,500 / mo',
    kyc_risk_score: 25,
    recent_transactions: [
      { id: 'TX-70561', amount: 10164, currency: 'USD', date: '2026-07-23T18:12:00Z', status: 'completed' },
      { id: 'TX-70560', amount: 420, currency: 'USD', date: '2026-07-15T12:00:00Z', status: 'completed' },
      { id: 'TX-70559', amount: 150, currency: 'USD', date: '2026-07-10T14:32:00Z', status: 'completed' }
    ],
    alerts: [
      { id: 'A-103', status: 'closed', date: '2026-07-24' }
    ]
  }
};

// API HELPER INTERFACE WITH LOCAL STORAGE SYNC
class LocalDB {
  static getAlerts(): Alert[] {
    const data = localStorage.getItem('fraud_alerts');
    if (!data) {
      localStorage.setItem('fraud_alerts', JSON.stringify(INITIAL_ALERTS));
      return INITIAL_ALERTS;
    }
    return JSON.parse(data);
  }

  static saveAlerts(alerts: Alert[]) {
    localStorage.setItem('fraud_alerts', JSON.stringify(alerts));
  }

  static getCustomers(): Record<string, CustomerProfile> {
    const data = localStorage.getItem('fraud_customers');
    if (!data) {
      localStorage.setItem('fraud_customers', JSON.stringify(CUSTOMERS_DB));
      return CUSTOMERS_DB;
    }
    return JSON.parse(data);
  }

  static saveCustomers(db: Record<string, CustomerProfile>) {
    localStorage.setItem('fraud_customers', JSON.stringify(db));
  }
}

// API CLIENT
export const api = {
  // Query Console
  executeQuery: async (query: string): Promise<FinalResponse> => {
    // Simulate real backend routing latency
    await new Promise((resolve) => setTimeout(resolve, 1000 + Math.random() * 500));
    
    const normalized = query.toLowerCase().trim();
    
    // Simple routing matching
    if (normalized.includes('structuring') || normalized.includes('pattern')) {
      return QUERY_RESPONSES[1];
    } else if (normalized.includes('10+') || normalized.includes('ten or more') || (normalized.includes('under') && normalized.includes('10,000') && normalized.includes('customers'))) {
      return QUERY_RESPONSES[2];
    } else if (normalized.includes('4521')) {
      return QUERY_RESPONSES[3];
    } else if (normalized.includes('123') || normalized.includes('spending')) {
      return QUERY_RESPONSES[4];
    } else if (normalized.includes('over 10,000') || normalized.includes('over $10,000') || normalized.includes('> 10000') || normalized.includes('over 10000')) {
      return QUERY_RESPONSES[5];
    } else if (normalized.includes('analyse') || normalized.includes('dataset') || normalized.includes('explore')) {
      return QUERY_RESPONSES[6];
    }
    
    // Fallback: Default informational response when no match is found
    return {
      contract_version: 'v1',
      request_id: `req-fallback-${Date.now()}`,
      generated_at: new Date().toISOString(),
      execution_summary: {
        query: query,
        detected_intent: 'explanation_request',
        route: 'simple_lookup',
        filters: { max_results: 100 },
        plan: null,
        tools_invoked: ['sql_lookup'],
        tools_skipped: [
          { tool: 'eda', reason: 'Specific scope requested without dataset metrics.' },
          { tool: 'feature_engineering', reason: 'Bypassed for general text query.' },
          { tool: 'anomaly_detection', reason: 'No structured analysis rules matches.' }
        ],
        fallbacks: [],
        warnings: []
      },
      results: [],
      supporting_evidence: [],
      charts: [],
      answer: 'No matching suspicious scenarios, entities, or transaction thresholds found for this scope. Try running one of the mandatory example queries.'
    };
  },

  // Alert Lifecycle API
  getAlerts: async (): Promise<Alert[]> => {
    return LocalDB.getAlerts();
  },

  updateAlertStatus: async (
    alertId: string, 
    newStatus: Alert['status'], 
    reviewer: string, 
    reason?: string
  ): Promise<Alert> => {
    const alerts = LocalDB.getAlerts();
    const alertIndex = alerts.findIndex(a => a.id === alertId);
    
    if (alertIndex === -1) {
      throw new Error('Alert not found');
    }
    
    const alert = alerts[alertIndex];
    const oldStatus = alert.status;
    
    // Validate state transitions
    // open -> in_review -> escalated/dismissed -> closed
    let isValid = false;
    if (oldStatus === 'open' && newStatus === 'in_review') isValid = true;
    if (oldStatus === 'in_review' && (newStatus === 'escalated' || newStatus === 'dismissed')) isValid = true;
    if ((oldStatus === 'escalated' || oldStatus === 'dismissed') && newStatus === 'closed') isValid = true;
    
    if (!isValid) {
      throw new Error(`Invalid status transition from ${oldStatus} to ${newStatus}`);
    }

    const timestamp = new Date().toISOString().replace('T', ' ').substring(0, 19) + 'Z';
    const auditLog: AuditLog = {
      timestamp,
      reviewer,
      transition: `${oldStatus} -> ${newStatus}`,
      reason: reason || undefined
    };

    const updatedAlert: Alert = {
      ...alert,
      status: newStatus,
      audit_history: [...alert.audit_history, auditLog]
    };

    alerts[alertIndex] = updatedAlert;
    LocalDB.saveAlerts(alerts);

    // Sync status change inside customer database as well if needed
    if (alert.entity_type === 'customer') {
      const customers = LocalDB.getCustomers();
      const customer = customers[alert.entity_id];
      if (customer) {
        customer.alerts = customer.alerts.map(a => a.id === alertId ? { ...a, status: newStatus } : a);
        LocalDB.saveCustomers(customers);
      }
    }

    return updatedAlert;
  },

  createAlertFromQuery: async (entityType: 'customer' | 'transaction', entityId: string, results: ResultItem[], evidence: ToolResult[]): Promise<Alert> => {
    const alerts = LocalDB.getAlerts();
    const existing = alerts.find(a => a.entity_id === entityId && a.entity_type === entityType && a.status !== 'closed');
    if (existing) {
      return existing;
    }

    const newId = `A-${100 + alerts.length + 1}`;
    
    // Determine risk level based on result score or mock
    let risk_level: 'LOW' | 'MEDIUM' | 'HIGH' = 'MEDIUM';
    const flagged = results.find(r => r.result_type === 'flagged') as FlaggedResult | undefined;
    if (flagged) {
      risk_level = flagged.risk_level;
    }

    const newAlert: Alert = {
      id: newId,
      risk_level,
      entity_type: entityType,
      entity_id: entityId,
      opened_at: new Date().toISOString(),
      status: 'open',
      age_description: 'Just now',
      results,
      supporting_evidence: evidence,
      audit_history: [
        {
          timestamp: new Date().toISOString().replace('T', ' ').substring(0, 19) + 'Z',
          reviewer: 'system',
          transition: 'open',
          reason: 'Auto-flagged from Investigation Console query execution.'
        }
      ]
    };

    alerts.push(newAlert);
    LocalDB.saveAlerts(alerts);

    // Sync inside Customer database
    if (entityType === 'customer') {
      const customers = LocalDB.getCustomers();
      const customer = customers[entityId];
      if (customer) {
        customer.alerts.push({ id: newId, status: 'open', date: new Date().toISOString().substring(0, 10) });
        LocalDB.saveCustomers(customers);
      }
    }

    return newAlert;
  },

  // Customer Profile API
  getCustomersList: async (): Promise<CustomerProfile[]> => {
    return Object.values(LocalDB.getCustomers());
  },

  getCustomerDetails: async (customerId: string): Promise<CustomerProfile | null> => {
    const db = LocalDB.getCustomers();
    return db[customerId] || null;
  }
};
