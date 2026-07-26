import React, { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { InvestigateView } from './views/InvestigateView';
import { AlertsView } from './views/AlertsView';
import { CustomersView } from './views/CustomersView';
import { api, DEMO_AS_OF } from './services/api';

function App() {
  const [currentView, setCurrentView] = useState<'investigate' | 'alerts' | 'customers'>('investigate');
  const [openAlertsCount, setOpenAlertsCount] = useState(0);
  const [apiLabel, setApiLabel] = useState('checking…');
  const [investigatePrefill, setInvestigatePrefill] = useState<string | null>(null);

  const updateAlertsBadge = async () => {
    try {
      const list = await api.getAlerts();
      const openCount = list.filter((a) => a.status !== 'closed' && a.status !== 'dismissed').length;
      setOpenAlertsCount(openCount);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    updateAlertsBadge();
    api
      .getHealth()
      .then((h) => setApiLabel(`Operational (${h.environment || h.status})`))
      .catch(() => setApiLabel('Unavailable — start FastAPI on :8000'));
  }, []);

  const openInvestigateForCustomer = (customerId: string) => {
    setInvestigatePrefill(`Is customer ID ${customerId} suspicious?`);
    setCurrentView('investigate');
  };

  const renderActiveView = () => {
    switch (currentView) {
      case 'investigate':
        return (
          <InvestigateView
            onAlertCreated={updateAlertsBadge}
            onOpenAlerts={() => setCurrentView('alerts')}
            initialQuery={investigatePrefill}
            onInitialQueryConsumed={() => setInvestigatePrefill(null)}
          />
        );
      case 'alerts':
        return (
          <AlertsView
            onAlertUpdated={updateAlertsBadge}
            onOpenInvestigation={(entityId) => openInvestigateForCustomer(entityId)}
          />
        );
      case 'customers':
        return <CustomersView onInvestigate={openInvestigateForCustomer} />;
      default:
        return <InvestigateView onAlertCreated={updateAlertsBadge} />;
    }
  };

  const getHeaderTitle = () => {
    switch (currentView) {
      case 'investigate':
        return 'AML Investigation Query Console';
      case 'alerts':
        return 'Compliance Alert Disposition Queue';
      case 'customers':
        return 'Customer Profile Lookup & Directory';
      default:
        return 'Investigation Console';
    }
  };

  return (
    <div className="app-container">
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        openAlertsCount={openAlertsCount}
      />

      <main className="main-content">
        <header className="top-header">
          <h1 className="view-title">{getHeaderTitle()}</h1>
          <div className="system-status">
            <span className="status-dot"></span>
            <span>API Status: {apiLabel}</span>
            <span style={{ margin: '0 8px', color: 'var(--border-color)' }}>|</span>
            <span>Demo as-of: {DEMO_AS_OF.replace('T', ' ').replace('Z', ' UTC')}</span>
          </div>
        </header>

        {renderActiveView()}
      </main>
    </div>
  );
}

export default App;
