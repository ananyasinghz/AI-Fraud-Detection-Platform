import React, { useState, useEffect, useRef } from 'react';
import {
  api,
  DEMO_AS_OF,
  FinalResponse,
  ResultItem,
  FlaggedResult,
  ChartSpec,
} from '../services/api';
import {
  ArrowRight,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  FileText,
  PlusCircle,
  Check,
  Copy,
} from 'lucide-react';
import {
  buildAlertCasePack,
  buildInvestigationPack,
  explanationFallbackCopy,
  explanationSourceBanner,
  extractEdaCohort,
  extractExplanation,
  extractFeatureResults,
  extractSpendComparison,
  extractSqlTransactions,
  extractThresholdCohort,
  flaggedResults,
  formatUsdFromMinor,
  hasEdaEvidence,
  hasPolicyContextOnly,
  keyFieldsFromTool,
  statusBanner,
} from '../utils/reviewer';

interface InvestigateViewProps {
  onAlertCreated: () => void;
  onOpenAlerts?: () => void;
  initialQuery?: string | null;
  onInitialQueryConsumed?: () => void;
}

const EXAMPLE_QUERIES = [
  {
    text: 'Show me transactions over $5,000',
    label: '1. SQL amount lookup',
    hint: 'Expect a transaction table (seed has rows ≥ $5k). SQL-only — no risk explanation.',
  },
  {
    text: 'Which customers made 10+ transactions under $10,000?',
    label: '2. Threshold aggregation',
    hint: 'Customer counts under $10k with ≥10 txs (not a raw txn dump).',
  },
  {
    text: 'Find structuring patterns for customer cus-dev-42-structuring-00 in the last 30 days',
    label: '3. Structuring (features+rules)',
    hint: 'Expect flagged MEDIUM/review, explanation card, evidence tools.',
  },
  {
    text: 'Is customer ID cus-dev-42-structuring-00 suspicious?',
    label: '4. Entity investigation',
    hint: 'Entity-scoped tools + Phase 8 risk/escalation/explanation.',
  },
  {
    text: 'Did customer cus-dev-42-spending-increase-00 suddenly increase spending this month?',
    label: '5. Feature-only spending',
    hint: 'Current vs prior 30d spend + elevated flag.',
  },
  {
    text: 'Analyse this dataset for suspicious activity',
    label: '6. Broad EDA exploration',
    hint: 'Cohort stats + charts (not an empty risk table).',
  },
];

export const InvestigateView: React.FC<InvestigateViewProps> = ({
  onAlertCreated,
  onOpenAlerts,
  initialQuery,
  onInitialQueryConsumed,
}) => {
  const [query, setQuery] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [response, setResponse] = useState<FinalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [isSummaryExpanded, setIsSummaryExpanded] = useState(true);
  const [isExamplesExpanded, setIsExamplesExpanded] = useState(true);
  const [hasRunQuery, setHasRunQuery] = useState(false);
  const [alertStates, setAlertStates] = useState<Record<string, { created: boolean; id?: string }>>(
    {},
  );
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  useEffect(() => {
    if (initialQuery && initialQuery.trim()) {
      setQuery(initialQuery);
      onInitialQueryConsumed?.();
      void runQuery(initialQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  const runQuery = async (queryText: string) => {
    if (!queryText.trim() || isRunning) return;

    setQuery(queryText);
    setIsRunning(true);
    setElapsedTime(0);
    setError(null);
    setResponse(null);
    setExpandedRows({});
    setHasRunQuery(true);
    setIsExamplesExpanded(false);
    setAlertStates({});

    const startTime = Date.now();
    timerRef.current = setInterval(() => {
      setElapsedTime(parseFloat(((Date.now() - startTime) / 1000).toFixed(1)));
    }, 100);

    try {
      const res = await api.executeQuery(queryText);
      setResponse(res);

      const flagged = flaggedResults(res);
      if (flagged.length > 0) {
        setExpandedRows({ [flagged[0].entity_id]: true });
      }

      const existingAlerts = await api.getAlerts();
      const updated: Record<string, { created: boolean; id?: string }> = {};
      flagged.forEach((r, idx) => {
        const matched = existingAlerts.find(
          (a) =>
            a.entity_id === r.entity_id &&
            a.entity_type === r.entity_type &&
            a.status !== 'closed',
        );
        if (matched) {
          updated[r.entity_id || `idx-${idx}`] = { created: true, id: matched.id };
        }
      });
      setAlertStates(updated);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Network error while executing query.';
      setError(message);
    } finally {
      setIsRunning(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void runQuery(query);
  };

  const toggleRow = (id: string) => {
    setExpandedRows((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const getRiskClass = (level: string) => {
    switch (level?.toUpperCase()) {
      case 'HIGH':
        return 'high';
      case 'MEDIUM':
        return 'medium';
      case 'LOW':
        return 'low';
      default:
        return '';
    }
  };

  const handleCreateAlert = async (entityId: string, result: ResultItem) => {
    if (!response || result.result_type !== 'flagged') return;
    try {
      const alert = await api.createAlertFromQuery(
        result.entity_type as 'customer' | 'transaction',
        entityId,
        response.results,
        response.supporting_evidence,
        buildAlertCasePack({
          response,
          flagged: result,
          query: response.execution_summary.query,
        }),
      );
      setAlertStates((prev) => ({
        ...prev,
        [entityId]: { created: true, id: alert.id },
      }));
      onAlertCreated();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to create alert');
    }
  };

  const downloadPack = () => {
    if (!response) return;
    const alertId =
      Object.values(alertStates).find((s) => s.created && s.id)?.id ||
      null;
    const pack = buildInvestigationPack({ response, demoAsOf: DEMO_AS_OF, alertId });
    const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `investigation-pack-${response.request_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(text);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      /* ignore */
    }
  };

  const renderSVGChart = (chart: ChartSpec) => {
    const labels = chart.data.labels || [];
    const values = (chart.data.values || []).map(Number);
    if (!labels.length || !values.length) {
      const rows = Array.isArray(chart.data.rows) ? chart.data.rows : null;
      if (rows && rows.length) {
        return (
          <div className="table-container" style={{ border: 'none', maxHeight: 220, overflow: 'auto' }}>
            <table className="console-table" style={{ fontSize: 11 }}>
              <tbody>
                {rows.slice(0, 20).map((row, i) => (
                  <tr key={i}>
                    {Array.isArray(row)
                      ? row.map((cell, j) => (
                          <td key={j} className="mono-cell">
                            {String(cell)}
                          </td>
                        ))
                      : Object.entries(row as Record<string, unknown>).map(([k, v]) => (
                          <td key={k} className="mono-cell">
                            {k}: {String(v)}
                          </td>
                        ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      return (
        <div className="mono-cell" style={{ fontSize: 11, padding: 8 }}>
          Table/chart payload: {JSON.stringify(chart.data).slice(0, 240)}
          {JSON.stringify(chart.data).length > 240 ? '…' : ''}
        </div>
      );
    }
    const chartHeight = 180;
    const chartWidth = Math.max(500, labels.length * 56);
    const maxVal = Math.max(...values, 1);
    const barWidth = Math.floor((chartWidth - 50) / labels.length);
    const formatVal = (v: number) =>
      Number.isInteger(v) ? String(v) : v.toLocaleString(undefined, { maximumFractionDigits: 2 });

    return (
      <div>
        {(chart.y_label || chart.x_label) && (
          <div className="chart-caption" style={{ marginBottom: 6, fontSize: 11, color: 'var(--text-muted)' }}>
            {[chart.y_label && `Y: ${chart.y_label}`, chart.x_label && `X: ${chart.x_label}`]
              .filter(Boolean)
              .join(' · ')}
          </div>
        )}
        <svg
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
          className="chart-canvas"
          style={{ width: '100%', height: 'auto', border: 'none' }}
          role="img"
          aria-label={chart.title}
        >
          <line
            x1="40"
            y1={chartHeight - 28}
            x2={chartWidth - 10}
            y2={chartHeight - 28}
            stroke="var(--text-muted)"
            strokeWidth="1"
          />
          <line x1="40" y1="16" x2="40" y2={chartHeight - 28} stroke="var(--text-muted)" strokeWidth="1" />
          {values.map((val, idx) => {
            const h = (val / maxVal) * (chartHeight - 56);
            const x = 48 + idx * barWidth;
            const y = chartHeight - 28 - h;
            const label = String(labels[idx] ?? '');
            const short = label.length > 10 ? `${label.slice(0, 9)}…` : label;
            return (
              <g key={idx}>
                <title>{`${label}: ${formatVal(val)}`}</title>
                <rect
                  x={x}
                  y={y}
                  width={Math.max(barWidth - 8, 4)}
                  height={Math.max(h, 1)}
                  fill="var(--accent-blue)"
                  opacity={0.85}
                />
                <text
                  x={x + Math.max(barWidth - 8, 4) / 2}
                  y={y - 4}
                  textAnchor="middle"
                  fontSize="9"
                  fill="var(--text-primary)"
                  fontFamily="var(--font-mono)"
                >
                  {formatVal(val)}
                </text>
                <text
                  x={x + Math.max(barWidth - 8, 4) / 2}
                  y={chartHeight - 10}
                  textAnchor="middle"
                  fontSize="9"
                  fill="var(--text-muted)"
                  fontFamily="var(--font-mono)"
                >
                  {short}
                </text>
              </g>
            );
          })}
          <text
            x="36"
            y="22"
            textAnchor="end"
            fontSize="9"
            fill="var(--text-muted)"
            fontFamily="var(--font-mono)"
          >
            {formatVal(maxVal)}
          </text>
        </svg>
      </div>
    );
  };

  const sqlRows = response ? extractSqlTransactions(response) : [];
  const featureRows = response ? extractFeatureResults(response) : [];
  const thresholdCohort = response ? extractThresholdCohort(response) : null;
  const edaCohort = response ? extractEdaCohort(response) : null;
  const spendComparison = response ? extractSpendComparison(response) : null;
  const flagged = response ? flaggedResults(response) : [];
  const explanation = response ? extractExplanation(response) : null;
  const banner = response ? statusBanner(response) : null;
  const sourceBanner = response ? explanationSourceBanner(response) : null;
  const policyNote = response ? hasPolicyContextOnly(response) : false;
  const chartCount = response?.charts?.length ?? 0;
  const showEmptyState =
    !!response &&
    flagged.length === 0 &&
    !edaCohort &&
    !hasEdaEvidence(response) &&
    !thresholdCohort &&
    !spendComparison &&
    featureRows.length === 0 &&
    sqlRows.length === 0 &&
    chartCount === 0;

  return (
    <div className="view-container">
      <div className="console-section">
        <form onSubmit={handleFormSubmit} className="query-bar-container">
          <input
            type="text"
            className="query-input"
            placeholder="Type an investigation query…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={isRunning}
          />
          <button type="submit" className="run-button" disabled={isRunning}>
            <ArrowRight size={14} />
            Execute
          </button>
        </form>

        {isRunning && (
          <div className="execution-status-bar">
            <span className="status-label-running">Running…</span>
            <span style={{ color: 'var(--text-muted)' }}>Elapsed: {elapsedTime}s</span>
          </div>
        )}

        {!isRunning && response && (
          <div className="execution-status-bar" style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="status-label-done">
              {response.status || 'completed'} in {elapsedTime || '—'}s
            </span>
            <button type="button" className="suggestion-btn" onClick={downloadPack} style={{ padding: '2px 8px' }}>
              <FileText size={12} style={{ display: 'inline', marginRight: 4 }} />
              Download investigation pack
            </button>
          </div>
        )}
      </div>

      {(!hasRunQuery || isExamplesExpanded) && (
        <div className="suggestions-box">
          <div
            className="suggestions-title"
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
            onClick={() => setIsExamplesExpanded(!isExamplesExpanded)}
          >
            <span>Example queries (Judge Demo)</span>
            <span>{isExamplesExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</span>
          </div>
          {isExamplesExpanded && (
            <div className="suggestions-list" style={{ marginTop: 8 }}>
              {EXAMPLE_QUERIES.map((q, idx) => (
                <div key={idx} style={{ marginBottom: 8 }}>
                  <button
                    type="button"
                    onClick={() => void runQuery(q.text)}
                    className="suggestion-btn"
                    disabled={isRunning}
                    style={{ display: 'block', width: '100%', textAlign: 'left' }}
                  >
                    <strong>{q.label}</strong>
                    <div style={{ fontSize: 11, opacity: 0.85, marginTop: 2 }}>{q.text}</div>
                  </button>
                  <div className="mono-cell" style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, paddingLeft: 4 }}>
                    {q.hint}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="error-banner">
          <AlertCircle size={14} style={{ display: 'inline', marginRight: 6 }} />
          {error}
        </div>
      )}

      {response && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {banner && banner.kind !== 'ok' && (
            <div className="error-banner" style={{ opacity: banner.kind === 'soft_partial' ? 0.9 : 1 }}>
              {banner.message}
            </div>
          )}
          {sourceBanner && (
            <div className="execution-status-bar" style={{ fontSize: 12 }}>
              {sourceBanner}
            </div>
          )}

          <div className="summary-panel">
            <div className="summary-header" onClick={() => setIsSummaryExpanded(!isSummaryExpanded)}>
              <span>Execution Summary</span>
              {isSummaryExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </div>
            {isSummaryExpanded && (
              <div className="summary-grid">
                <span className="summary-key">Query</span>
                <span className="summary-val">{response.execution_summary.query}</span>
                <span className="summary-key">Intent</span>
                <span className="summary-val">{response.execution_summary.detected_intent}</span>
                <span className="summary-key">Route</span>
                <span className="summary-val">{response.execution_summary.route}</span>
                <span className="summary-key">Filters</span>
                <span className="summary-val mono-cell" style={{ fontSize: 11 }}>
                  {JSON.stringify(response.execution_summary.filters)}
                </span>
                <span className="summary-key">Invoked</span>
                <span className="summary-val">
                  {(response.execution_summary.tools_invoked || []).join(', ') || '—'}
                </span>
                <span className="summary-key">Skipped</span>
                <span className="summary-val">
                  {(response.execution_summary.tools_skipped || [])
                    .map((s) => `${s.tool} (${s.reason})`)
                    .join(' · ') || '—'}
                </span>
                <span className="summary-key">Warnings</span>
                <span className="summary-val">
                  {(response.execution_summary.warnings || []).join(' · ') || '—'}
                </span>
              </div>
            )}
          </div>

          {/* Typed results */}
          <div className="summary-panel" style={{ background: '#fff' }}>
            <div className="summary-header">Investigation Results</div>

            {flagged.length > 0 && (
              <div className="table-container" style={{ border: 'none' }}>
                <div className="detail-section-title">Flagged entities</div>
                <table className="console-table">
                  <thead>
                    <tr>
                      <th style={{ width: 40 }} />
                      <th>Entity</th>
                      <th>ID</th>
                      <th>Risk</th>
                      <th>Score</th>
                      <th>Reasons</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {flagged.map((result) => {
                      const id = result.entity_id;
                      const isExpanded = !!expandedRows[id];
                      const created = alertStates[id]?.created;
                      return (
                        <React.Fragment key={id}>
                          <tr>
                            <td>
                              <button type="button" className="suggestion-btn" onClick={() => toggleRow(id)}>
                                {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                              </button>
                            </td>
                            <td>{result.entity_type}</td>
                            <td className="mono-cell">{result.entity_id}</td>
                            <td>
                              <span className={`risk-badge ${getRiskClass(result.risk_level)}`}>
                                {result.risk_level}
                              </span>
                            </td>
                            <td>{result.risk_score.toFixed(1)}</td>
                            <td style={{ fontSize: 12 }}>{result.reasons.join('; ') || '—'}</td>
                            <td>
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
                                <span className="mono-cell" style={{ textTransform: 'uppercase', fontSize: 11 }}>
                                  Rec: {result.escalation_action}
                                </span>
                                {created ? (
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
                                    <span style={{ color: '#16a34a', display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                                      <Check size={14} /> Alert {alertStates[id].id}
                                    </span>
                                    {onOpenAlerts && (
                                      <button
                                        type="button"
                                        className="secondary-btn"
                                        style={{ padding: '4px 8px', fontSize: 11 }}
                                        onClick={() => onOpenAlerts()}
                                      >
                                        Open Alerts
                                      </button>
                                    )}
                                  </div>
                                ) : (
                                  <button
                                    type="button"
                                    className="primary-btn"
                                    style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '6px 10px', fontSize: 12 }}
                                    onClick={() => void handleCreateAlert(id, result)}
                                  >
                                    <PlusCircle size={14} /> Create Alert Case
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr>
                              <td colSpan={7}>
                                <div className="drawer-actions" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8 }}>
                                  <div>
                                    Confidence: {(result.confidence * 100).toFixed(0)}% · Evidence refs:{' '}
                                    {result.evidence_refs.join(', ') || '—'}
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
                <div
                  style={{
                    margin: '10px 12px 12px',
                    padding: '10px 12px',
                    border: '1px solid var(--border-color)',
                    borderRadius: 4,
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 10,
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    Recommended: <strong className="mono-cell">{flagged[0].escalation_action}</strong>.
                    Create an alert case to send this finding to the disposition queue.
                  </div>
                  {alertStates[flagged[0].entity_id]?.created ? (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span style={{ color: '#16a34a', fontSize: 12 }}>
                        <Check size={14} style={{ display: 'inline', marginRight: 4 }} />
                        Alert {alertStates[flagged[0].entity_id].id}
                      </span>
                      {onOpenAlerts && (
                        <button type="button" className="primary-btn" style={{ padding: '6px 10px', fontSize: 12 }} onClick={() => onOpenAlerts()}>
                          Open Alerts
                        </button>
                      )}
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="primary-btn"
                      style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '6px 12px', fontSize: 12 }}
                      onClick={() => void handleCreateAlert(flagged[0].entity_id, flagged[0])}
                    >
                      <PlusCircle size={14} /> Create Alert Case
                    </button>
                  )}
                </div>
              </div>
            )}

            {flagged.length === 0 && edaCohort && (
              <div className="table-container" style={{ border: 'none' }}>
                <div className="detail-section-title">EDA / cohort summary</div>
                <table className="console-table">
                  <tbody>
                    <tr>
                      <td className="mono-cell">Transactions</td>
                      <td>{edaCohort.transaction_count ?? '—'}</td>
                    </tr>
                    <tr>
                      <td className="mono-cell">Customers</td>
                      <td>{edaCohort.customer_count ?? '—'}</td>
                    </tr>
                    <tr>
                      <td className="mono-cell">Amount min / mean / max</td>
                      <td className="mono-cell">
                        {edaCohort.amount_min_minor != null
                          ? formatUsdFromMinor(edaCohort.amount_min_minor)
                          : '—'}{' '}
                        /{' '}
                        {edaCohort.amount_mean_minor != null
                          ? formatUsdFromMinor(Math.round(edaCohort.amount_mean_minor))
                          : '—'}{' '}
                        /{' '}
                        {edaCohort.amount_max_minor != null
                          ? formatUsdFromMinor(edaCohort.amount_max_minor)
                          : '—'}
                      </td>
                    </tr>
                    <tr>
                      <td className="mono-cell">Segments</td>
                      <td style={{ fontSize: 12 }}>
                        {Object.keys(edaCohort.segment_counts).length
                          ? Object.entries(edaCohort.segment_counts)
                              .map(([k, v]) => `${k}: ${v}`)
                              .join(' · ')
                          : '—'}
                      </td>
                    </tr>
                    {edaCohort.chart_titles.length > 0 && (
                      <tr>
                        <td className="mono-cell">Charts</td>
                        <td style={{ fontSize: 12 }}>{edaCohort.chart_titles.join(' · ')}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {flagged.length === 0 && !edaCohort && thresholdCohort && (
              <div className="table-container" style={{ border: 'none' }}>
                <div className="detail-section-title">
                  Customers meeting threshold (≥{thresholdCohort.minimum_count}
                  {thresholdCohort.amount_max ? ` under $${thresholdCohort.amount_max}` : ''}) —{' '}
                  {thresholdCohort.total_matching} match
                </div>
                {thresholdCohort.customers.length === 0 ? (
                  <div className="mono-cell" style={{ padding: 12, fontSize: 12 }}>
                    No customers met the count threshold in the resolved scope.
                  </div>
                ) : (
                  <table className="console-table">
                    <thead>
                      <tr>
                        <th>Customer</th>
                        <th>Transaction count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {thresholdCohort.customers.map((row) => (
                        <tr key={row.customer_id}>
                          <td className="mono-cell">{row.customer_id}</td>
                          <td className="mono-cell">{row.transaction_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {flagged.length === 0 && !edaCohort && !thresholdCohort && spendComparison && (
              <div className="table-container" style={{ border: 'none' }}>
                <div className="detail-section-title">Spend comparison (30d current vs prior)</div>
                <table className="console-table">
                  <thead>
                    <tr>
                      <th>Customer</th>
                      <th>Current</th>
                      <th>Prior</th>
                      <th>Delta</th>
                      <th>Ratio</th>
                      <th>Elevated</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="mono-cell">{spendComparison.entityId}</td>
                      <td>{formatUsdFromMinor(spendComparison.currentMinor)}</td>
                      <td>{formatUsdFromMinor(spendComparison.priorMinor)}</td>
                      <td>{formatUsdFromMinor(spendComparison.deltaMinor)}</td>
                      <td className="mono-cell">
                        {spendComparison.ratio != null
                          ? `${spendComparison.ratio.toFixed(2)}x`
                          : 'n/a'}
                      </td>
                      <td>
                        <span className={`risk-badge ${spendComparison.elevated ? 'high' : 'low'}`}>
                          {spendComparison.elevated ? 'YES' : 'NO'}
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}

            {flagged.length === 0 &&
              !edaCohort &&
              !thresholdCohort &&
              !spendComparison &&
              featureRows.length > 0 && (
                <div className="table-container" style={{ border: 'none' }}>
                  <div className="detail-section-title">Feature results</div>
                  <table className="console-table">
                    <thead>
                      <tr>
                        <th>Operation</th>
                        <th>Window</th>
                        <th>Entity</th>
                        <th>Values</th>
                      </tr>
                    </thead>
                    <tbody>
                      {featureRows.map((f, idx) => (
                        <tr key={idx}>
                          <td className="mono-cell">{f.operation}</td>
                          <td className="mono-cell">{f.windowRole || '—'}</td>
                          <td className="mono-cell">{f.entityHint}</td>
                          <td style={{ fontSize: 12 }}>{f.summary}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

            {flagged.length === 0 &&
              !edaCohort &&
              !thresholdCohort &&
              featureRows.length === 0 &&
              sqlRows.length > 0 && (
                <div className="table-container" style={{ border: 'none' }}>
                  <div className="detail-section-title">
                    Transactions ({sqlRows.length}
                    {sqlRows.length >= 100 ? ', showing first 100' : ''})
                  </div>
                  <table className="console-table">
                    <thead>
                      <tr>
                        <th>Transaction</th>
                        <th>Customer</th>
                        <th>Amount</th>
                        <th>Currency</th>
                        <th>Date</th>
                        <th>Type</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sqlRows.slice(0, 100).map((tx) => (
                        <tr key={tx.transaction_id}>
                          <td className="mono-cell">{tx.transaction_id}</td>
                          <td className="mono-cell">{tx.customer_id}</td>
                          <td>{formatUsdFromMinor(tx.amount_minor, tx.currency)}</td>
                          <td>{tx.currency}</td>
                          <td className="mono-cell" style={{ fontSize: 11 }}>
                            {tx.occurred_at.replace('T', ' ').slice(0, 19)}
                          </td>
                          <td>{tx.transaction_type}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

            {showEmptyState && (
              <div className="empty-state" style={{ padding: 16 }}>
                No transaction, feature, cohort, or flagged rows for this query scope.
                {response.results[0]?.result_type === 'informational' && (
                  <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
                    Note: {response.results[0].summary}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Compliance explanation */}
          <div className="summary-panel" style={{ background: '#fff' }}>
            <div className="summary-header">Compliance explanation</div>
            {explanation ? (
              <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>
                  <strong>Risk level:</strong> {explanation.riskLevel}
                  {explanation.riskScore != null && (
                    <> · Score: {explanation.riskScore.toFixed(1)}/100</>
                  )}
                  {explanation.confidence != null && (
                    <> · Confidence: {(explanation.confidence * 100).toFixed(0)}%</>
                  )}
                </div>
                <div>
                  <strong>Escalation:</strong> {explanation.escalationAction}
                </div>
                {explanation.reasons.length > 0 && (
                  <div>
                    <div className="detail-section-title">Findings</div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {explanation.reasons.map((r, i) => (
                        <li key={i} style={{ fontSize: 13 }}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {explanation.recommendedAction && (
                  <div>
                    <div className="detail-section-title">Recommended action</div>
                    <div style={{ fontSize: 13 }}>{explanation.recommendedAction}</div>
                  </div>
                )}
                {explanation.summary && (
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{explanation.summary}</div>
                )}
                <div className="mono-cell" style={{ fontSize: 11 }}>
                  Evidence IDs: {explanation.evidenceIds.join(', ') || '—'}
                </div>
                <div className="mono-cell" style={{ fontSize: 11 }}>
                  Source: {explanation.source}
                </div>
              </div>
            ) : (
              <div style={{ padding: 12, fontSize: 13, color: 'var(--text-muted)' }}>
                {explanationFallbackCopy(response)}
              </div>
            )}
          </div>

          {/* Evidence panel */}
          <div className="summary-panel" style={{ background: '#fff' }}>
            <div className="summary-header">Supporting evidence</div>
            {policyNote && (
              <div className="mono-cell" style={{ padding: '8px 12px 0', fontSize: 11, color: 'var(--text-muted)' }}>
                Policy excerpts only — not case facts (POLICY_CONTEXT_ONLY).
              </div>
            )}
            {(response.supporting_evidence || []).length === 0 ? (
              <div className="empty-state" style={{ padding: 12 }}>No tool evidence for this run.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 12 }}>
                {response.supporting_evidence.map((tool, idx) => (
                  <div key={`${tool.tool}-${idx}`} style={{ borderTop: '1px solid var(--border-color)', paddingTop: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                      <strong className="mono-cell">
                        {tool.tool}.{tool.operation} · {tool.status}
                      </strong>
                      <span className="mono-cell" style={{ fontSize: 11 }}>
                        {tool.duration_ms}ms
                      </span>
                    </div>
                    <div style={{ marginTop: 4 }}>
                      {keyFieldsFromTool(tool).map((kv) => (
                        <div key={kv.label} className="mono-cell" style={{ fontSize: 11 }}>
                          {kv.label}: {kv.value}
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                      {(tool.evidence || []).map((ref) => (
                        <button
                          key={ref.evidence_id}
                          type="button"
                          className="suggestion-btn"
                          style={{ fontSize: 10, padding: '2px 6px' }}
                          onClick={() => void copyText(ref.evidence_id)}
                          title="Copy evidence id"
                        >
                          <Copy size={10} style={{ display: 'inline', marginRight: 4 }} />
                          {ref.evidence_id}
                          {copiedId === ref.evidence_id ? ' ✓' : ''}
                        </button>
                      ))}
                      {!tool.evidence?.length && (
                        <button
                          type="button"
                          className="suggestion-btn"
                          style={{ fontSize: 10, padding: '2px 6px' }}
                          onClick={() => void copyText(`${tool.tool}.${tool.operation}`)}
                        >
                          <Copy size={10} style={{ display: 'inline', marginRight: 4 }} />
                          {tool.tool}.{tool.operation}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {response.charts && response.charts.length > 0 && (
            <div className="charts-section">
              {response.charts.map((chart) => (
                <div key={chart.chart_id} className="chart-card">
                  <div className="chart-title">{chart.title}</div>
                  {renderSVGChart(chart)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
