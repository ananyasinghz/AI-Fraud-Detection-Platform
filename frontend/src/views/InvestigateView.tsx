import React, { useState, useEffect, useRef } from 'react';
import { api, FinalResponse, ResultItem, ToolResult, FlaggedResult } from '../services/api';
import { ArrowRight, ChevronDown, ChevronUp, AlertCircle, FileText, PlusCircle, Check } from 'lucide-react';

interface InvestigateViewProps {
  onAlertCreated: () => void;
}

export const InvestigateView: React.FC<InvestigateViewProps> = ({ onAlertCreated }) => {
  const [query, setQuery] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [response, setResponse] = useState<FinalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [isSummaryExpanded, setIsSummaryExpanded] = useState(true);
  const [isExamplesExpanded, setIsExamplesExpanded] = useState(true);
  const [hasRunQuery, setHasRunQuery] = useState(false);
  const [alertStates, setAlertStates] = useState<Record<string, { created: boolean; id?: string }>>({});

  const timerRef = useRef<any | null>(null);

  const exampleQueries = [
    { text: 'Find structuring patterns in the last 30 days', label: '1. Structuring Patterns (Full Investigate)' },
    { text: 'Which customers made 10+ transactions under $10,000?', label: '2. 10+ Tx Under $10k (SQL Threshold)' },
    { text: 'Is customer ID 4521 suspicious?', label: '3. Customer C-4521 Profile (Full Investigate)' },
    { text: 'Did customer 123 suddenly increase spending this month?', label: '4. Spending Spike (Feature Only)' },
    { text: 'Show me transactions over $10,000', label: '5. Tx Over $10k (SQL Direct Filter)' },
    { text: 'Analyse this dataset for suspicious activity', label: '6. Bulk Dataset Sweep (Full Investigate)' }
  ];

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const runQuery = async (queryText: string) => {
    if (!queryText.trim() || isRunning) return;

    setQuery(queryText);
    setIsRunning(true);
    setElapsedTime(0);
    setError(null);
    setResponse(null);
    setExpandedRows({});
    setHasRunQuery(true);
    setIsExamplesExpanded(false); // Collapse examples once run
    setAlertStates({});

    const startTime = Date.now();
    timerRef.current = setInterval(() => {
      setElapsedTime(parseFloat(((Date.now() - startTime) / 1000).toFixed(1)));
    }, 100);

    try {
      const res = await api.executeQuery(queryText);
      setResponse(res);
      
      // Auto-expand first result row if available for convenience
      if (res.results && res.results.length > 0) {
        const firstId = res.results[0].entity_id || 'row-0';
        setExpandedRows({ [firstId]: true });
      }

      // Check if alert already exists for flagged entities
      const existingAlerts = await api.getAlerts();
      const updatedAlertStates: Record<string, { created: boolean; id?: string }> = {};
      res.results.forEach((r, idx) => {
        if (r.result_type === 'flagged') {
          const matchedAlert = existingAlerts.find(a => a.entity_id === r.entity_id && a.entity_type === r.entity_type && a.status !== 'closed');
          if (matchedAlert) {
            updatedAlertStates[r.entity_id || `idx-${idx}`] = { created: true, id: matchedAlert.id };
          }
        }
      });
      setAlertStates(updatedAlertStates);
    } catch (err: any) {
      console.error(err);
      setError(err?.message || 'A network error occurred while executing the query.');
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
    runQuery(query);
  };

  const toggleRow = (id: string) => {
    setExpandedRows(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const getRiskClass = (level: string) => {
    switch (level?.toUpperCase()) {
      case 'HIGH': return 'high';
      case 'MEDIUM': return 'medium';
      case 'LOW': return 'low';
      default: return '';
    }
  };

  const handleCreateAlert = async (entityId: string, result: ResultItem) => {
    if (!response || result.result_type !== 'flagged') return;

    try {
      // Find supporting evidence containing matching evidence refs
      const matchedEvidence = response.supporting_evidence.filter(ev => 
        result.evidence_refs.includes(ev.tool) || 
        ev.evidence.some(ref => result.evidence_refs.includes(ref.evidence_id))
      );

      const alert = await api.createAlertFromQuery(
        result.entity_type as 'customer' | 'transaction',
        entityId,
        [result],
        matchedEvidence
      );

      setAlertStates(prev => ({
        ...prev,
        [entityId]: { created: true, id: alert.id }
      }));
      
      onAlertCreated(); // Refresh badge count in sidebar
    } catch (err) {
      console.error(err);
      alert('Failed to generate alert record.');
    }
  };

  // Extract matching details from supporting evidence
  const renderEvidenceDetails = (refs: string[]) => {
    if (!response) return null;
    
    // Find all evidence details from supporting tools matching the references
    const evidenceItems: Array<{ id: string; label: string; tool: string; value: string; provenance: string }> = [];

    response.supporting_evidence.forEach((toolResult: ToolResult) => {
      toolResult.evidence.forEach(ref => {
        if (refs.includes(ref.evidence_id)) {
          // Resolve JSON value path simply
          let val = '—';
          if (ref.json_path === '$.rolling_count') val = String(toolResult.data.rolling_count ?? '—');
          else if (ref.json_path === '$.rules_fired') val = Array.isArray(toolResult.data.rules_fired) ? toolResult.data.rules_fired.join(', ') : '—';
          else if (ref.json_path === '$.velocity_index') val = String(toolResult.data.velocity_index ?? '—');
          else if (ref.json_path === '$.occupation_deviation_score') val = String(toolResult.data.occupation_deviation_score ?? '—');
          else if (ref.json_path === '$.ml_score') val = String(toolResult.data.ml_score ?? '—');
          else if (ref.json_path === '$.records') val = toolResult.data.records ? `${toolResult.data.records.length} records matched` : '—';
          else if (ref.json_path === '$.matches') val = toolResult.data.matches ? `${toolResult.data.matches.length} aggregation rows` : '—';
          else if (ref.json_path === '$.total_transactions') val = String(toolResult.data.total_transactions ?? '—');
          else if (ref.json_path === '$.total_flagged_entities') val = String(toolResult.data.total_flagged_entities ?? '—');

          evidenceItems.push({
            id: ref.evidence_id,
            label: ref.label,
            tool: toolResult.tool,
            value: val,
            provenance: `${toolResult.provenance.source} (${toolResult.provenance.query_or_version})`
          });
        }
      });
    });

    if (evidenceItems.length === 0) {
      return <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>No additional evidence items found for: {refs.join(', ')}</div>;
    }

    return (
      <table className="evidence-table">
        <thead>
          <tr>
            <th>Ref ID</th>
            <th>Indicator Metric</th>
            <th>Value</th>
            <th>Source System / Provenance</th>
          </tr>
        </thead>
        <tbody>
          {evidenceItems.map(item => (
            <tr key={item.id}>
              <td>{item.id}</td>
              <td>{item.label}</td>
              <td style={{ fontWeight: '600' }}>{item.value}</td>
              <td style={{ color: 'var(--text-muted)', fontSize: '11px' }}>{item.provenance}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  // Render minimal SVG-based charts to match the "boring on purpose" design system
  const renderSVGChart = (chart: any) => {
    const { labels, values } = chart.data;
    if (!labels || !values || labels.length === 0) return null;

    const chartHeight = 150;
    const chartWidth = 500;
    const maxVal = Math.max(...values, 1);
    const barWidth = Math.floor((chartWidth - 40) / labels.length);

    if (chart.chart_type === 'line') {
      const points = values.map((val: number, idx: number) => {
        const x = 30 + idx * ((chartWidth - 50) / (labels.length - 1));
        const y = chartHeight - 20 - (val / maxVal) * (chartHeight - 40);
        return `${x},${y}`;
      }).join(' ');

      return (
        <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="chart-canvas" style={{ width: '100%', height: 'auto', border: 'none' }}>
          {/* Gridlines */}
          <line x1="30" y1="20" x2={chartWidth - 20} y2="20" stroke="var(--border-color)" strokeWidth="0.5" strokeDasharray="2,2" />
          <line x1="30" y1="65" x2={chartWidth - 20} y2="65" stroke="var(--border-color)" strokeWidth="0.5" strokeDasharray="2,2" />
          <line x1="30" y1="110" x2={chartWidth - 20} y2="110" stroke="var(--border-color)" strokeWidth="0.5" strokeDasharray="2,2" />
          
          {/* Y Axis Labels */}
          <text x="25" y="24" textAnchor="end" fontSize="9" fontFamily="var(--font-mono)" fill="var(--text-muted)">{maxVal}</text>
          <text x="25" y="69" textAnchor="end" fontSize="9" fontFamily="var(--font-mono)" fill="var(--text-muted)">{Math.floor(maxVal / 2)}</text>
          <text x="25" y="114" textAnchor="end" fontSize="9" fontFamily="var(--font-mono)" fill="var(--text-muted)">0</text>
          
          {/* Axes */}
          <line x1="30" y1="10" x2="30" y2={chartHeight - 20} stroke="var(--text-muted)" strokeWidth="1" />
          <line x1="30" y1={chartHeight - 20} x2={chartWidth - 10} y2={chartHeight - 20} stroke="var(--text-muted)" strokeWidth="1" />

          {/* Line Path */}
          <polyline fill="none" stroke="var(--accent-blue)" strokeWidth="1.5" points={points} />
          
          {/* Scatter Points */}
          {values.map((val: number, idx: number) => {
            const x = 30 + idx * ((chartWidth - 50) / (labels.length - 1));
            const y = chartHeight - 20 - (val / maxVal) * (chartHeight - 40);
            return (
              <circle key={idx} cx={x} cy={y} r="2.5" fill="var(--text-primary)" stroke="var(--accent-blue)" strokeWidth="1" />
            );
          })}

          {/* X Axis Labels */}
          {labels.map((label: string, idx: number) => {
            const x = 30 + idx * ((chartWidth - 50) / (labels.length - 1));
            return (
              <text key={idx} x={x} y={chartHeight - 5} textAnchor="middle" fontSize="9" fontFamily="var(--font-mono)" fill="var(--text-muted)">
                {label}
              </text>
            );
          })}
        </svg>
      );
    }

    // Default: Bar Chart
    return (
      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="chart-canvas" style={{ width: '100%', height: 'auto', border: 'none' }}>
        {/* Gridlines */}
        <line x1="30" y1="20" x2={chartWidth - 20} y2="20" stroke="var(--border-color)" strokeWidth="0.5" strokeDasharray="2,2" />
        <line x1="30" y1="65" x2={chartWidth - 20} y2="65" stroke="var(--border-color)" strokeWidth="0.5" strokeDasharray="2,2" />
        <line x1="30" y1="110" x2={chartWidth - 20} y2="110" stroke="var(--border-color)" strokeWidth="0.5" strokeDasharray="2,2" />
        
        {/* Y Axis Labels */}
        <text x="25" y="24" textAnchor="end" fontSize="9" fontFamily="var(--font-mono)" fill="var(--text-muted)">{maxVal}</text>
        <text x="25" y="69" textAnchor="end" fontSize="9" fontFamily="var(--font-mono)" fill="var(--text-muted)">{Math.floor(maxVal / 2)}</text>
        <text x="25" y="114" textAnchor="end" fontSize="9" fontFamily="var(--font-mono)" fill="var(--text-muted)">0</text>
        
        {/* Axes */}
        <line x1="30" y1="10" x2="30" y2={chartHeight - 20} stroke="var(--text-muted)" strokeWidth="1" />
        <line x1="30" y1={chartHeight - 20} x2={chartWidth - 10} y2={chartHeight - 20} stroke="var(--text-muted)" strokeWidth="1" />

        {/* Bars */}
        {values.map((val: number, idx: number) => {
          const barHeight = (val / maxVal) * (chartHeight - 40);
          const x = 35 + idx * ((chartWidth - 45) / labels.length);
          const y = chartHeight - 20 - barHeight;
          const w = Math.max(10, ((chartWidth - 45) / labels.length) - 10);
          return (
            <g key={idx}>
              <rect x={x} y={y} width={w} height={barHeight} fill="var(--accent-blue)" stroke="none" />
              <text x={x + w/2} y={y - 3} textAnchor="middle" fontSize="8" fontFamily="var(--font-mono)" fill="var(--text-secondary)">{val}</text>
            </g>
          );
        })}

        {/* X Axis Labels */}
        {labels.map((label: string, idx: number) => {
          const x = 35 + idx * ((chartWidth - 45) / labels.length) + (Math.max(10, ((chartWidth - 45) / labels.length) - 10) / 2);
          return (
            <text key={idx} x={x} y={chartHeight - 5} textAnchor="middle" fontSize="9" fontFamily="var(--font-mono)" fill="var(--text-muted)">
              {label}
            </text>
          );
        })}
      </svg>
    );
  };

  // Determine if risk/recommendation columns are required based on results contents
  const hasRiskColumns = response?.results && response.results.some(r => r.result_type === 'flagged');

  return (
    <div className="view-container">
      {/* Console Input Bar */}
      <div className="console-section">
        <form onSubmit={handleFormSubmit} className="query-bar-container">
          <input
            type="text"
            className="query-input"
            placeholder="Type search queries (e.g. Find structuring patterns in the last 30 days)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={isRunning}
          />
          <button type="submit" className="run-button" disabled={isRunning}>
            <ArrowRight size={14} />
            Execute
          </button>
        </form>

        {/* Running loader status */}
        {isRunning && (
          <div className="execution-status-bar">
            <span className="status-label-running">Running…</span>
            <span style={{ color: 'var(--text-muted)' }}>Elapsed: {elapsedTime}s</span>
          </div>
        )}

        {!isRunning && response && (
          <div className="execution-status-bar">
            <span className="status-label-done">Done in {elapsedTime || 1.1}s</span>
          </div>
        )}
      </div>

      {/* Example Queries box */}
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
            <div className="suggestions-list" style={{ marginTop: '8px' }}>
              {exampleQueries.map((q, idx) => (
                <button
                  key={idx}
                  onClick={() => runQuery(q.text)}
                  className="suggestion-btn"
                  disabled={isRunning}
                >
                  {q.label}: "{q.text}"
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Collapse Examples Toggle link if already run */}
      {hasRunQuery && !isExamplesExpanded && (
        <button 
          onClick={() => setIsExamplesExpanded(true)}
          className="suggestion-btn"
          style={{ alignSelf: 'flex-start', padding: 0 }}
        >
          + Show Example Queries
        </button>
      )}

      {/* Error banner */}
      {error && (
        <div className="error-banner">
          <AlertCircle size={14} style={{ display: 'inline', marginRight: '6px', verticalAlign: 'middle' }} />
          Network error: {error}
        </div>
      )}

      {/* Execution Summary Panel */}
      {response && (
        <div className="summary-panel">
          <div className="summary-header" onClick={() => setIsSummaryExpanded(!isSummaryExpanded)}>
            <span>Execution Summary Tracing</span>
            <span>{isSummaryExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</span>
          </div>
          {isSummaryExpanded && (
            <div className="summary-grid">
              <span className="summary-key">Query</span>
              <span className="summary-val" style={{ fontFamily: 'var(--font-sans)', fontWeight: '500' }}>
                {response.execution_summary.query}
              </span>

              <span className="summary-key">Intent</span>
              <span className="summary-val">{response.execution_summary.detected_intent}</span>

              <span className="summary-key">Route</span>
              <span className="summary-val">{response.execution_summary.route}</span>

              <span className="summary-key">Filters</span>
              <span className="summary-val">
                {Object.entries(response.execution_summary.filters)
                  .filter(([_, v]) => v !== null && (!Array.isArray(v) || v.length > 0))
                  .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                  .join(' · ') || '—'}
              </span>

              <span className="summary-key">Invoked</span>
              <span className="summary-val">
                {response.execution_summary.tools_invoked.length > 0 ? (
                  response.execution_summary.tools_invoked.map(tool => (
                    <span key={tool} className="tool-chip invoked">{tool}</span>
                  ))
                ) : '—'}
              </span>

              <span className="summary-key">Skipped</span>
              <span className="summary-val">
                {response.execution_summary.tools_skipped.length > 0 ? (
                  response.execution_summary.tools_skipped.map((skip, idx) => (
                    <div key={idx} style={{ marginBottom: '4px' }}>
                      <span className="tool-chip skipped">{skip.tool}</span>
                      <span className="skipped-reason">{skip.reason}</span>
                    </div>
                  ))
                ) : '—'}
              </span>

              <span className="summary-key">Warnings</span>
              <span className="summary-val" style={{ color: 'var(--risk-med-text)' }}>
                {response.execution_summary.warnings.join(' · ') || '—'}
              </span>

              {response.execution_summary.fallbacks.length > 0 && (
                <>
                  <span className="summary-key">Fallback</span>
                  <span className="summary-val" style={{ color: 'var(--risk-high-text)' }}>
                    Fallback used: {response.execution_summary.fallbacks.join(', ')}
                  </span>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* Main Results Console */}
      {response && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Warning/Degraded banner for fallbacks */}
          {response.execution_summary.fallbacks.length > 0 && (
            <div className="error-banner">
              Fallback used: deterministic template (LLM unavailable)
            </div>
          )}

          {/* Results Table */}
          <div className="summary-panel" style={{ background: '#fff' }}>
            <div className="summary-header">Investigation Results</div>
            
            {response.results.length > 0 ? (
              <div className="table-container" style={{ border: 'none' }}>
                <table className="console-table">
                  <thead>
                    <tr>
                      <th style={{ width: '40px' }}></th>
                      <th>Entity</th>
                      <th>ID</th>
                      {hasRiskColumns && (
                        <>
                          <th>Risk</th>
                          <th>Score</th>
                        </>
                      )}
                      <th>Summary/Rules fired</th>
                      {hasRiskColumns && <th>Recommendation</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {response.results.map((result, idx) => {
                      const id = result.entity_id || `row-${idx}`;
                      const isExpanded = !!expandedRows[id];
                      const isFlagged = result.result_type === 'flagged';
                      const flagged = result as FlaggedResult;

                      return (
                        <React.Fragment key={id}>
                          <tr 
                            className={`clickable ${isExpanded ? 'expanded' : ''}`}
                            onClick={() => toggleRow(id)}
                          >
                            <td>
                              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </td>
                            <td style={{ textTransform: 'capitalize' }}>
                              {result.entity_type || '—'}
                            </td>
                            <td className="mono-cell">
                              {result.entity_id || '—'}
                            </td>
                            {hasRiskColumns && (
                              <>
                                <td>
                                  {isFlagged ? (
                                    <span className={`risk-badge ${getRiskClass(flagged.risk_level)}`}>
                                      {flagged.risk_level}
                                    </span>
                                  ) : '—'}
                                </td>
                                <td className="mono-cell">
                                  {isFlagged ? flagged.risk_score : '—'}
                                </td>
                              </>
                            )}
                            <td>
                              {isFlagged ? flagged.reasons.join(', ') : result.summary}
                            </td>
                            {hasRiskColumns && (
                              <td>
                                {isFlagged ? (
                                  <span style={{ 
                                    textTransform: 'uppercase', 
                                    fontWeight: '600', 
                                    fontSize: '11px',
                                    color: flagged.escalation_action === 'report' ? 'var(--risk-high-text)' : 'var(--risk-med-text)'
                                  }}>
                                    {flagged.escalation_action}
                                  </span>
                                ) : '—'}
                              </td>
                            )}
                          </tr>
                          
                          {/* Expanded Details Pane */}
                          {isExpanded && (
                            <tr>
                              <td colSpan={hasRiskColumns ? 7 : 5} style={{ padding: 0 }}>
                                <div className="detail-drawer">
                                  {isFlagged && (
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: '20px' }}>
                                      <div>
                                        <div className="detail-section-title">Risk classification triggers</div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                          {flagged.reasons.map((reason, rIdx) => (
                                            <div key={rIdx} className="reason-item">
                                              <span className="mono-cell" style={{ fontWeight: '500' }}>· {reason}</span>
                                              {flagged.evidence_refs[rIdx] && (
                                                <span className="evidence-ref-link">
                                                  {flagged.evidence_refs[rIdx]}
                                                </span>
                                              )}
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                      <div>
                                        <div className="detail-section-title">Risk thresholds & calibration</div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
                                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                            <span style={{ color: 'var(--text-muted)' }}>Risk scoring weight:</span>
                                            <span>{flagged.risk_score}/100</span>
                                          </div>
                                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                            <span style={{ color: 'var(--text-muted)' }}>Decision confidence:</span>
                                            <span>{Math.floor(flagged.confidence * 100)}%</span>
                                          </div>
                                        </div>
                                      </div>
                                    </div>
                                  )}

                                  {/* Evidence Reference Table */}
                                  <div>
                                    <div className="detail-section-title">Supporting Evidence References</div>
                                    {renderEvidenceDetails(result.evidence_refs)}
                                  </div>

                                  {/* Explanation Block */}
                                  <div>
                                    <div className="explanation-label">Grounded Narrative Explanation</div>
                                    <div className="explanation-block">
                                      {response.answer}
                                    </div>
                                  </div>

                                  {/* Escalation/Alert Action Box */}
                                  {isFlagged && (
                                    <div className="drawer-actions">
                                      <div>
                                        <span style={{ color: 'var(--text-muted)', fontSize: '11px' }}>ESCALATION: </span>
                                        <span className="mono-cell" style={{ fontWeight: '600', textTransform: 'uppercase' }}>
                                          {flagged.escalation_action}
                                        </span>
                                      </div>
                                      
                                      {alertStates[result.entity_id] && alertStates[result.entity_id].created ? (
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#16a34a', fontWeight: '500' }}>
                                          <Check size={14} />
                                          Alert generated ({alertStates[result.entity_id].id})
                                        </span>
                                      ) : (
                                        <button 
                                          className="primary-btn"
                                          style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                                          onClick={() => handleCreateAlert(result.entity_id || '', result)}
                                        >
                                          <PlusCircle size={14} />
                                          Create Alert Case
                                        </button>
                                      )}
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-state">No matching transactions or customers found for this query scope.</div>
            )}
          </div>

          {/* Charts Panel */}
          {response.charts && response.charts.length > 0 && (
            <div className="charts-section">
              {response.charts.map(chart => (
                <div key={chart.chart_id} className="chart-card">
                  <div className="chart-title">{chart.title}</div>
                  
                  {renderSVGChart(chart)}
                  
                  {chart.x_label && chart.y_label && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0 30px', fontSize: '9px', color: 'var(--text-muted)', marginTop: '2px', fontFamily: 'var(--font-mono)' }}>
                      <span>X: {chart.x_label}</span>
                      <span>Y: {chart.y_label}</span>
                    </div>
                  )}

                  <div className="chart-caption">
                    Caption: {chart.title} (lineage refs: {chart.evidence_refs.join(', ')})
                  </div>
                </div>
              ))}
            </div>
          )}

        </div>
      )}
    </div>
  );
};
