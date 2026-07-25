import React from 'react';
import { AlertTriangle, Terminal, Users } from 'lucide-react';

interface SidebarProps {
  currentView: 'investigate' | 'alerts' | 'customers';
  onViewChange: (view: 'investigate' | 'alerts' | 'customers') => void;
  openAlertsCount: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onViewChange,
  openAlertsCount
}) => {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        DETECTION PLATFORM
      </div>
      <nav className="sidebar-nav">
        <button
          onClick={() => onViewChange('investigate')}
          className={`nav-item ${currentView === 'investigate' ? 'active' : ''}`}
          style={{ background: 'none', border: 'none', width: '100%', cursor: 'pointer', textAlign: 'left' }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Terminal size={14} />
            Investigate
          </span>
        </button>

        <button
          onClick={() => onViewChange('alerts')}
          className={`nav-item ${currentView === 'alerts' ? 'active' : ''}`}
          style={{ background: 'none', border: 'none', width: '100%', cursor: 'pointer', textAlign: 'left' }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertTriangle size={14} />
            Alerts
          </span>
          {openAlertsCount > 0 && (
            <span className="nav-badge">{openAlertsCount}</span>
          )}
        </button>

        <button
          onClick={() => onViewChange('customers')}
          className={`nav-item ${currentView === 'customers' ? 'active' : ''}`}
          style={{ background: 'none', border: 'none', width: '100%', cursor: 'pointer', textAlign: 'left' }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Users size={14} />
            Customers
          </span>
        </button>
      </nav>
    </aside>
  );
};
