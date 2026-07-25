import React, { useState, useEffect } from 'react';
import { api, Alert, ResultItem, ToolResult } from '../services/api';
import { ShieldAlert, RefreshCw, CheckCircle2, ChevronRight, FileSpreadsheet } from 'lucide-react';

interface AlertsViewProps {
  onAlertUpdated: () => void;
}

export const AlertsView: React.FC<AlertsViewProps> = ({ onAlertUpdated }) => {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [reasonText, setReasonText] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchAlerts = async () => {
    try {
      const list = await api.getAlerts();
      // Default sort by risk level desc, then age/opened_at
      const sorted = [...list].sort((a, b) => {
        const riskWeights = { HIGH: 3, MEDIUM: 2, LOW: 1 };
        const aRisk = riskWeights[a.risk_level] || 0;
        const bRisk = riskWeights[b.risk_level] || 0;
        if (aRisk !== bRisk) return bRisk - aRisk;
        return new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime();
      });
      setAlerts(sorted);
      
      if (sorted.length > 0 && !selectedAlertId) {
        setSelectedAlertId(sorted[0].id);
      }
    } catch (err) {
      console.error('Failed to load alerts', err);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, [selectedAlertId]);

  useEffect(() => {
    if (selectedAlertId) {
      const match = alerts.find(a => a.id === selectedAlertId);
      setSelectedAlert(match || null);
      setReasonText(''); // Reset textarea on selection change
    } else {
      setSelectedAlert(null);
    }
  }, [selectedAlertId, alerts]);

  const handleStatusTransition = async (newStatus: Alert['status']) => {
    if (!selectedAlert) return;
    
    // Validate reason requirement for dismiss and escalate
    if ((newStatus === 'dismissed' || newStatus === 'escalated') && !reasonText.trim()) {
      alert('A justification reason is required for escalation or dismissal.');
      return;
    }

    setLoading(true);
    try {
      const updated = await api.updateAlertStatus(
        selectedAlert.id,
        newStatus,
        'reviewer_1', // Single demo identity
        reasonText.trim() || undefined
      );
      
      setReasonText('');
      await fetchAlerts(); // Refresh lists
      onAlertUpdated(); // Callback to parent
    } catch (err: any) {
      console.error(err);
      alert(err.message || 'Failed to update alert state.');
    } finally {
      setLoading(false);
    }
  };

  const getRiskClass = (level: string) => {
    switch (level?.toUpperCase()) {
      case 'HIGH': return 'high';
      case 'MEDIUM': return 'medium';
      case 'LOW': return 'low';
      default: return '';
    }
  };

  // Helper to render evidence indicators
  const renderEvidenceDetails = (evidence: ToolResult[]) => {
    if (!evidence || evidence.length === 0) return <span>No raw evidence records.</span>;
    
    return (
      <table className="evidence-table" style={{ fontSize: '11px' }}>
        <thead>
          <tr>
            <th>Tool</th>
            <th>Operation</th>
            <th>Indicator</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          {evidence.flatMap(toolRes => 
            toolRes.evidence.map(ref => {
              let val = '—';
              if (ref.json_path === '$.rolling_count') val = String(toolRes.data.rolling_count ?? '—');
              else if (ref.json_path === '$.rules_fired') val = Array.isArray(toolRes.data.rules_fired) ? toolRes.data.rules_fired.join(', ') : '—';
              else if (ref.json_path === '$.velocity_index') val = String(toolRes.data.velocity_index ?? '—');
              else if (ref.json_path === '$.occupation_deviation_score') val = String(toolRes.data.occupation_deviation_score ?? '—');
              else if (ref.json_path === '$.ml_score') val = String(toolRes.data.ml_score ?? '—');

              return (
                <tr key={ref.evidence_id}>
                  <td>{toolRes.tool}</td>
                  <td>{toolRes.operation}</td>
                  <td>{ref.label}</td>
                  <td style={{ fontWeight: '600' }}>{val}</td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    );
  };

  // Validation helpers for transitions
  const canTransitionTo = (target: Alert['status']) => {
    if (!selectedAlert) return false;
    const current = selectedAlert.status;
    if (current === 'open' && target === 'in_review') return true;
    if (current === 'in_review' && (target === 'escalated' || target === 'dismissed')) return true;
    if ((current === 'escalated' || current === 'dismissed') && target === 'closed') return true;
    return false;
  };

  return (
    <div className="view-container">
      {alerts.length === 0 ? (
        <div className="empty-state">No suspicious activity alerts currently in the queue.</div>
      ) : (
        <div className="alerts-layout">
          
          {/* Left Side: Alerts Queue Table */}
          <div className="summary-panel" style={{ background: '#fff' }}>
            <div className="summary-header">Reviewer Alert Queue ({alerts.filter(a => a.status !== 'closed').length} active)</div>
            <div className="table-container" style={{ border: 'none' }}>
              <table className="console-table">
                <thead>
                  <tr>
                    <th>Alert ID</th>
                    <th>Risk</th>
                    <th>Entity</th>
                    <th>Opened</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.map(alert => (
                    <tr 
                      key={alert.id}
                      className={`clickable ${selectedAlertId === alert.id ? 'expanded' : ''}`}
                      onClick={() => setSelectedAlertId(alert.id)}
                    >
                      <td className="mono-cell" style={{ fontWeight: '600' }}>{alert.id}</td>
                      <td>
                        <span className={`risk-badge ${getRiskClass(alert.risk_level)}`}>
                          {alert.risk_level}
                        </span>
                      </td>
                      <td className="mono-cell" style={{ textTransform: 'capitalize' }}>
                        {alert.entity_type}:{alert.entity_id}
                      </td>
                      <td>{alert.age_description}</td>
                      <td>
                        <span className="mono-cell" style={{ 
                          textTransform: 'uppercase', 
                          fontSize: '11px',
                          fontWeight: '500',
                          color: alert.status === 'open' ? 'var(--risk-high-text)' : alert.status === 'in_review' ? 'var(--risk-med-text)' : 'var(--text-muted)'
                        }}>
                          {alert.status}
                        </span>
                      </td>
                      <td>
                        <ChevronRight size={14} style={{ opacity: selectedAlertId === alert.id ? 1 : 0.3 }} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right Side: Alert Audit Panel */}
          {selectedAlert ? (
            <div className="alert-detail-panel">
              <div className="alert-detail-header">
                <span className="mono-cell" style={{ fontWeight: 'bold' }}>AUDIT PANEL: {selectedAlert.id}</span>
                <span className={`risk-badge ${getRiskClass(selectedAlert.risk_level)}`}>
                  {selectedAlert.risk_level}
                </span>
              </div>
              <div className="alert-detail-body">
                
                {/* Stepper progress bar */}
                <div>
                  <div className="detail-section-title">Case lifecycle status</div>
                  <div className="status-stepper">
                    <span className={`step-node ${selectedAlert.status === 'open' ? 'active' : ''}`}>open</span>
                    <span className="step-arrow">→</span>
                    <span className={`step-node ${selectedAlert.status === 'in_review' ? 'active' : ''}`}>in_review</span>
                    <span className="step-arrow">→</span>
                    <span className={`step-node ${['escalated', 'dismissed'].includes(selectedAlert.status) ? 'active' : ''}`}>
                      {['escalated', 'dismissed'].includes(selectedAlert.status) ? selectedAlert.status : 'escalated/dismissed'}
                    </span>
                    <span className="step-arrow">→</span>
                    <span className={`step-node ${selectedAlert.status === 'closed' ? 'active' : ''}`}>closed</span>
                  </div>
                </div>

                {/* Evidence table */}
                <div>
                  <div className="detail-section-title">Verified indicator evidence</div>
                  {renderEvidenceDetails(selectedAlert.supporting_evidence)}
                </div>

                {/* Reasons List */}
                <div>
                  <div className="detail-section-title">Primary triggers</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {selectedAlert.results.map((r, idx) => (
                      <div key={idx} className="reason-item mono-cell" style={{ fontSize: '12px' }}>
                        · {r.result_type === 'flagged' ? r.reasons.join(', ') : r.summary}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Action Buttons & Textarea (if not closed) */}
                {selectedAlert.status !== 'closed' && (
                  <div className="alert-actions-card">
                    <div className="detail-section-title" style={{ margin: 0 }}>Log decision action</div>
                    
                    {/* Reason input for dismiss or escalate */}
                    {['open', 'in_review'].includes(selectedAlert.status) && (
                      <textarea
                        className="reason-textarea"
                        placeholder="Add required audit justification reasoning..."
                        value={reasonText}
                        onChange={(e) => setReasonText(e.target.value)}
                        disabled={loading}
                      />
                    )}

                    <div className="action-buttons-row">
                      {/* open -> in_review */}
                      {canTransitionTo('in_review') && (
                        <button
                          className="primary-btn"
                          disabled={loading}
                          onClick={() => handleStatusTransition('in_review')}
                        >
                          Acknowledge & Review
                        </button>
                      )}

                      {/* in_review -> escalated */}
                      {canTransitionTo('escalated') && (
                        <button
                          className="warning-btn"
                          disabled={loading || !reasonText.trim()}
                          onClick={() => handleStatusTransition('escalated')}
                          title={!reasonText.trim() ? "Reason is required to escalate" : ""}
                        >
                          Escalate Case
                        </button>
                      )}

                      {/* in_review -> dismissed */}
                      {canTransitionTo('dismissed') && (
                        <button
                          className="secondary-btn"
                          disabled={loading || !reasonText.trim()}
                          onClick={() => handleStatusTransition('dismissed')}
                          title={!reasonText.trim() ? "Reason is required to dismiss" : ""}
                        >
                          Dismiss Alert
                        </button>
                      )}

                      {/* escalated/dismissed -> closed */}
                      {canTransitionTo('closed') && (
                        <button
                          className="primary-btn"
                          disabled={loading}
                          onClick={() => handleStatusTransition('closed')}
                          style={{ width: '100%' }}
                        >
                          Resolve & Close Alert
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Audit history logs */}
                <div>
                  <div className="detail-section-title">Case history audit trail</div>
                  <div className="audit-log-container">
                    {selectedAlert.audit_history.slice().reverse().map((log, idx) => (
                      <div key={idx} className="audit-log-row">
                        <span className="audit-time">[{log.timestamp}]</span>{' '}
                        <strong>{log.reviewer}</strong>: {log.transition}
                        {log.reason && (
                          <div className="audit-reason">Reason: {log.reason}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

              </div>
            </div>
          ) : (
            <div className="empty-state">Select an alert case to begin compliance auditing.</div>
          )}

        </div>
      )}
    </div>
  );
};
