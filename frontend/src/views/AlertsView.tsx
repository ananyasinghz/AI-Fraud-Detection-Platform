import React, { useState, useEffect } from 'react';
import { api, Alert, ToolResult } from '../services/api';
import { keyFieldsFromTool } from '../utils/reviewer';
import { ChevronRight } from 'lucide-react';

type DetailTab = 'summary' | 'evidence' | 'explanation' | 'history';

interface AlertsViewProps {
  onAlertUpdated: () => void;
  onOpenInvestigation?: (entityId: string, entityType: string) => void;
}

export const AlertsView: React.FC<AlertsViewProps> = ({ onAlertUpdated, onOpenInvestigation }) => {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [reasonText, setReasonText] = useState('');
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<DetailTab>('summary');

  const fetchAlerts = async () => {
    try {
      const list = await api.getAlerts();
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
      const match = alerts.find((a) => a.id === selectedAlertId);
      setSelectedAlert(match || null);
      setReasonText('');
      setActiveTab('summary');
    } else {
      setSelectedAlert(null);
    }
  }, [selectedAlertId, alerts]);

  const handleStatusTransition = async (newStatus: Alert['status']) => {
    if (!selectedAlert) return;

    if ((newStatus === 'dismissed' || newStatus === 'escalated') && !reasonText.trim()) {
      alert('A justification reason is required for escalation or dismissal.');
      return;
    }

    setLoading(true);
    try {
      await api.updateAlertStatus(
        selectedAlert.id,
        newStatus,
        'reviewer_1',
        reasonText.trim() || undefined,
      );
      setReasonText('');
      await fetchAlerts();
      onAlertUpdated();
    } catch (err: unknown) {
      console.error(err);
      alert(err instanceof Error ? err.message : 'Failed to update alert state.');
    } finally {
      setLoading(false);
    }
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

  const canTransitionTo = (target: Alert['status']) => {
    if (!selectedAlert) return false;
    const current = selectedAlert.status;
    const allowed: Record<Alert['status'], Alert['status'][]> = {
      open: ['in_review', 'escalated', 'dismissed', 'closed'],
      in_review: ['escalated', 'dismissed', 'closed'],
      escalated: ['in_review', 'dismissed', 'closed'],
      dismissed: ['closed'],
      closed: [],
    };
    return allowed[current]?.includes(target) ?? false;
  };

  const pack = selectedAlert?.case_pack;
  const packVersion =
    pack && typeof pack.pack_version === 'string' ? pack.pack_version : null;
  const flaggedFromPack =
    pack && pack.flagged_result && typeof pack.flagged_result === 'object'
      ? (pack.flagged_result as Record<string, unknown>)
      : null;
  const packExplanation =
    pack && pack.explanation && typeof pack.explanation === 'object'
      ? (pack.explanation as Record<string, unknown>)
      : null;
  const packEvidence: ToolResult[] = Array.isArray(pack?.supporting_evidence)
    ? (pack!.supporting_evidence as ToolResult[])
    : selectedAlert?.supporting_evidence || [];
  const packEvidenceRefs = Array.isArray(pack?.supporting_evidence_refs)
    ? (pack!.supporting_evidence_refs as Array<Record<string, unknown>>)
    : [];
  const flaggedEvidenceRefs = Array.isArray(flaggedFromPack?.evidence_refs)
    ? (flaggedFromPack!.evidence_refs as string[])
    : [];

  const mergedExplanation = (() => {
    if (!packExplanation && !flaggedFromPack) return null;
    const expl = packExplanation || {};
    return {
      summary: String(
        expl.summary ||
          (Array.isArray(flaggedFromPack?.reasons)
            ? (flaggedFromPack!.reasons as string[]).join('; ')
            : '') ||
          '—',
      ),
      reasons: Array.isArray(expl.reasons)
        ? (expl.reasons as string[])
        : Array.isArray(flaggedFromPack?.reasons)
          ? (flaggedFromPack!.reasons as string[])
          : [],
      riskLevel: String(
        expl.riskLevel ||
          expl.risk_level ||
          flaggedFromPack?.risk_level ||
          selectedAlert?.risk_level ||
          '—',
      ),
      riskScore:
        expl.riskScore ??
        expl.risk_score ??
        flaggedFromPack?.risk_score ??
        selectedAlert?.risk_score ??
        null,
      escalationAction: String(
        expl.escalationAction ||
          expl.escalation_action ||
          flaggedFromPack?.escalation_action ||
          selectedAlert?.escalation_action ||
          '—',
      ),
      recommendedAction: String(
        expl.recommendedAction || expl.recommended_action_explanation || '',
      ),
      source: String(expl.source || '—'),
      evidenceIds: Array.isArray(expl.evidenceIds)
        ? (expl.evidenceIds as string[])
        : Array.isArray(expl.evidence_ids)
          ? (expl.evidence_ids as string[])
          : flaggedEvidenceRefs,
    };
  })();

  const renderSummaryTab = () => {
    if (!selectedAlert) return null;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div>
          <div className="detail-section-title">Case lifecycle status</div>
          <div className="status-stepper">
            <span className={`step-node ${selectedAlert.status === 'open' ? 'active' : ''}`}>open</span>
            <span className="step-arrow">→</span>
            <span className={`step-node ${selectedAlert.status === 'in_review' ? 'active' : ''}`}>
              in_review
            </span>
            <span className="step-arrow">→</span>
            <span
              className={`step-node ${['escalated', 'dismissed'].includes(selectedAlert.status) ? 'active' : ''}`}
            >
              {['escalated', 'dismissed'].includes(selectedAlert.status)
                ? selectedAlert.status
                : 'escalated/dismissed'}
            </span>
            <span className="step-arrow">→</span>
            <span className={`step-node ${selectedAlert.status === 'closed' ? 'active' : ''}`}>closed</span>
          </div>
        </div>

        <div className="profile-field">
          <span className="profile-field-key">Entity</span>
          <span className="profile-field-val mono-cell">
            {selectedAlert.entity_type}:{selectedAlert.entity_id}
          </span>
        </div>
        <div className="profile-field">
          <span className="profile-field-key">Risk</span>
          <span className="profile-field-val">
            <span className={`risk-badge ${getRiskClass(selectedAlert.risk_level)}`}>
              {selectedAlert.risk_level}
            </span>{' '}
            <span className="mono-cell">{selectedAlert.risk_score.toFixed(2)}</span>
          </span>
        </div>
        <div className="profile-field">
          <span className="profile-field-key">Escalation</span>
          <span className="profile-field-val mono-cell">{selectedAlert.escalation_action}</span>
        </div>
        <div className="profile-field">
          <span className="profile-field-key">Snapshot ref</span>
          <span className="profile-field-val mono-cell">
            {selectedAlert.evidence_snapshot_ref || '—'}
          </span>
        </div>

        {onOpenInvestigation && selectedAlert.entity_type === 'customer' && (
          <button
            type="button"
            className="primary-btn"
            onClick={() => onOpenInvestigation(selectedAlert.entity_id, selectedAlert.entity_type)}
          >
            Open investigation
          </button>
        )}

        {selectedAlert.status !== 'closed' && (
          <div className="alert-actions-card">
            <div className="detail-section-title" style={{ margin: 0 }}>
              Log decision action
            </div>
            {['open', 'in_review'].includes(selectedAlert.status) && (
              <>
                <textarea
                  className="reason-textarea"
                  placeholder="Add required audit justification reasoning..."
                  value={reasonText}
                  onChange={(e) => setReasonText(e.target.value)}
                  disabled={loading}
                />
                <div
                  className="mono-cell"
                  style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: -4 }}
                >
                  Reason required to enable Escalate / Dismiss.
                </div>
              </>
            )}
            <div className="action-buttons-row">
              {canTransitionTo('in_review') && (
                <button
                  className="primary-btn"
                  disabled={loading}
                  onClick={() => handleStatusTransition('in_review')}
                >
                  Acknowledge & Review
                </button>
              )}
              {canTransitionTo('escalated') && (
                <button
                  className="warning-btn"
                  disabled={loading || !reasonText.trim()}
                  onClick={() => handleStatusTransition('escalated')}
                  title={!reasonText.trim() ? 'Reason is required to escalate' : ''}
                >
                  Escalate Case
                </button>
              )}
              {canTransitionTo('dismissed') && (
                <button
                  className="secondary-btn"
                  disabled={loading || !reasonText.trim()}
                  onClick={() => handleStatusTransition('dismissed')}
                  title={!reasonText.trim() ? 'Reason is required to dismiss' : ''}
                >
                  Dismiss Alert
                </button>
              )}
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
      </div>
    );
  };

  const renderEvidenceTab = () => {
    if (packEvidence.length > 0) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {packEvidence.map((tool, idx) => {
            const keys = keyFieldsFromTool(tool);
            return (
              <div key={`${tool.tool}-${idx}`} className="reason-item" style={{ fontSize: '12px' }}>
                <div className="mono-cell" style={{ fontWeight: 600 }}>
                  {tool.tool} / {tool.operation} — {tool.status}
                  {tool.duration_ms != null ? ` (${tool.duration_ms}ms)` : ''}
                </div>
                {keys.length > 0 && (
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: '11px' }}>
                    {keys.map((kv) => (
                      <li key={kv.label}>
                        <strong>{kv.label}:</strong> {kv.value}
                      </li>
                    ))}
                  </ul>
                )}
                {Array.isArray(tool.evidence) && tool.evidence.length > 0 && (
                  <div className="mono-cell" style={{ marginTop: 4, fontSize: 11 }}>
                    IDs: {tool.evidence.map((e) => e.evidence_id).join(', ')}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      );
    }

    if (packEvidenceRefs.length > 0) {
      return (
        <div className="table-container" style={{ border: 'none' }}>
          <table className="console-table" style={{ fontSize: 12 }}>
            <thead>
              <tr>
                <th>Tool</th>
                <th>Operation</th>
                <th>Status</th>
                <th>Evidence IDs</th>
              </tr>
            </thead>
            <tbody>
              {packEvidenceRefs.map((ref, idx) => {
                const evidence = Array.isArray(ref.evidence)
                  ? (ref.evidence as Array<Record<string, unknown>>)
                  : [];
                return (
                  <tr key={idx}>
                    <td className="mono-cell">{String(ref.tool || '—')}</td>
                    <td className="mono-cell">{String(ref.operation || '—')}</td>
                    <td className="mono-cell">{String(ref.status || '—')}</td>
                    <td className="mono-cell" style={{ fontSize: 11 }}>
                      {evidence
                        .map((e) => String(e.evidence_id || e.label || ''))
                        .filter(Boolean)
                        .join(', ') || '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      );
    }

    if (flaggedEvidenceRefs.length > 0) {
      return (
        <div style={{ fontSize: 13 }}>
          <div className="detail-section-title">Evidence refs from flagged result</div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {flaggedEvidenceRefs.map((id) => (
              <li key={id} className="mono-cell" style={{ fontSize: 12 }}>
                {id}
              </li>
            ))}
          </ul>
        </div>
      );
    }

    if (!pack) {
      return (
        <div className="mono-cell" style={{ fontSize: '12px', opacity: 0.75 }}>
          Pack missing — snapshot ref {selectedAlert?.evidence_snapshot_ref || '—'}. Re-open from a
          full Investigate create, or use Open investigation.
        </div>
      );
    }

    return (
      <div className="mono-cell" style={{ fontSize: '12px', opacity: 0.75 }}>
        No evidence in this pack (manual/smoke alert with empty supporting_evidence). Use Open
        investigation to re-run tools, or create the alert from a flagged Investigate result.
      </div>
    );
  };

  const renderExplanationTab = () => {
    if (!mergedExplanation) {
      return (
        <div className="mono-cell" style={{ fontSize: '12px', opacity: 0.75 }}>
          No explanation or flagged finding stored in this case pack. See Summary or Open
          investigation.
        </div>
      );
    }
    const score =
      typeof mergedExplanation.riskScore === 'number'
        ? mergedExplanation.riskScore.toFixed(1)
        : String(mergedExplanation.riskScore ?? '—');
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
        <div>
          <strong>Summary:</strong> {mergedExplanation.summary}
        </div>
        <div className="mono-cell">
          Risk: {mergedExplanation.riskLevel} · Score: {score} · Escalation:{' '}
          {mergedExplanation.escalationAction} · Source: {mergedExplanation.source}
        </div>
        {mergedExplanation.reasons.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {mergedExplanation.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
        {mergedExplanation.recommendedAction && (
          <div>
            <strong>Recommended action:</strong> {mergedExplanation.recommendedAction}
          </div>
        )}
        {mergedExplanation.evidenceIds.length > 0 && (
          <div className="mono-cell" style={{ fontSize: 11 }}>
            Evidence IDs: {mergedExplanation.evidenceIds.join(', ')}
          </div>
        )}
      </div>
    );
  };

  const renderHistoryTab = () => {
    if (!selectedAlert) return null;
    if (!selectedAlert.audit_history.length) {
      return (
        <div className="mono-cell" style={{ fontSize: 12, opacity: 0.75 }}>
          No disposition events yet.
        </div>
      );
    }
    return (
      <div className="audit-log-container">
        {selectedAlert.audit_history
          .slice()
          .reverse()
          .map((log, idx) => (
            <div key={idx} className="audit-log-row">
              <span className="audit-time">[{log.timestamp}]</span>{' '}
              <strong>{log.reviewer}</strong>: {log.transition}
              {log.reason && <div className="audit-reason">Reason: {log.reason}</div>}
            </div>
          ))}
      </div>
    );
  };

  const tabs: { id: DetailTab; label: string }[] = [
    { id: 'summary', label: 'Summary' },
    { id: 'evidence', label: 'Evidence' },
    { id: 'explanation', label: 'Explanation' },
    { id: 'history', label: 'History' },
  ];

  return (
    <div className="view-container">
      {alerts.length === 0 ? (
        <div className="empty-state">No suspicious activity alerts currently in the queue.</div>
      ) : (
        <div className="alerts-layout">
          <div className="summary-panel" style={{ background: '#fff' }}>
            <div className="summary-header">
              Reviewer Alert Queue ({alerts.filter((a) => a.status !== 'closed').length} active)
            </div>
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
                  {alerts.map((alert) => (
                    <tr
                      key={alert.id}
                      className={`clickable ${selectedAlertId === alert.id ? 'expanded' : ''}`}
                      onClick={() => setSelectedAlertId(alert.id)}
                    >
                      <td className="mono-cell" style={{ fontWeight: '600' }}>
                        {alert.id}
                      </td>
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
                        <span
                          className="mono-cell"
                          style={{
                            textTransform: 'uppercase',
                            fontSize: '11px',
                            fontWeight: '500',
                            color:
                              alert.status === 'open'
                                ? 'var(--risk-high-text)'
                                : alert.status === 'in_review'
                                  ? 'var(--risk-med-text)'
                                  : 'var(--text-muted)',
                          }}
                        >
                          {alert.status}
                        </span>
                      </td>
                      <td>
                        <ChevronRight
                          size={14}
                          style={{ opacity: selectedAlertId === alert.id ? 1 : 0.3 }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {selectedAlert ? (
            <div className="alert-detail-panel">
              <div className="alert-detail-header">
                <span className="mono-cell" style={{ fontWeight: 'bold' }}>
                  CASE FILE: {selectedAlert.id}
                </span>
                <span className={`risk-badge ${getRiskClass(selectedAlert.risk_level)}`}>
                  {selectedAlert.risk_level}
                </span>
              </div>
              <div className="alert-detail-body">
                <div className="case-file-tabs" role="tablist" aria-label="Case file sections">
                  {tabs.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={activeTab === tab.id}
                      className={`case-file-tab ${activeTab === tab.id ? 'active' : ''}`}
                      onClick={() => setActiveTab(tab.id)}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div
                  className="mono-cell"
                  style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: -8 }}
                >
                  Viewing: <strong>{activeTab}</strong>
                  {' · '}
                  Pack: {packVersion || 'none'}
                  {' · '}
                  Snapshot: {selectedAlert.evidence_snapshot_ref || '—'}
                </div>
                <div key={activeTab} className="case-file-tab-panel" role="tabpanel">
                  {activeTab === 'summary' && renderSummaryTab()}
                  {activeTab === 'evidence' && renderEvidenceTab()}
                  {activeTab === 'explanation' && renderExplanationTab()}
                  {activeTab === 'history' && renderHistoryTab()}
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
