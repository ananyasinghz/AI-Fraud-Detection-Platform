import React, { useState, useEffect } from 'react';
import { api, CustomerProfile } from '../services/api';
import { Search } from 'lucide-react';

export const CustomersView: React.FC = () => {
  const [searchId, setSearchId] = useState('');
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [customer, setCustomer] = useState<CustomerProfile | null>(null);
  const [allCustomers, setAllCustomers] = useState<CustomerProfile[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchCustomers = async () => {
      try {
        const list = await api.getCustomersList();
        setAllCustomers(list);
        // Default to C-4521 for demo ease
        if (list.length > 0) {
          setSelectedCustomerId(list[0].id);
        }
      } catch (err) {
        console.error(err);
        setError('Failed to fetch customers list');
      }
    };
    fetchCustomers();
  }, []);

  useEffect(() => {
    const fetchDetails = async () => {
      if (!selectedCustomerId) return;
      try {
        const details = await api.getCustomerDetails(selectedCustomerId);
        setCustomer(details);
      } catch (err) {
        console.error(err);
        setError('Failed to load customer details');
      }
    };
    fetchDetails();
  }, [selectedCustomerId]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const query = searchId.trim().toUpperCase();
    if (!query) return;

    const match = allCustomers.find(c => c.id.toUpperCase() === query || c.id.toUpperCase().includes(query));
    if (match) {
      setSelectedCustomerId(match.id);
      setError(null);
    } else {
      setError(`No customer found matching "${searchId}"`);
      setCustomer(null);
    }
  };

  const getRiskClass = (rating: string) => {
    switch (rating) {
      case 'HIGH': return 'high';
      case 'MEDIUM': return 'medium';
      default: return 'low';
    }
  };

  return (
    <div className="view-container">
      <div className="console-section">
        <form onSubmit={handleSearchSubmit} className="query-bar-container">
          <input
            type="text"
            className="query-input"
            placeholder="Search customer by ID (e.g. cus-dev-42-…)"
            value={searchId}
            onChange={(e) => setSearchId(e.target.value)}
          />
          <button type="submit" className="run-button">
            <Search size={12} />
            Search
          </button>
        </form>
        {error && <div className="error-banner" style={{ marginTop: '8px' }}>{error}</div>}
      </div>

      <div className="customer-profile-grid">
        {/* Left Side: Directory / Quick Profile */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div className="profile-card">
            <h3 className="suggestions-title">Customer Directory</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
              {allCustomers.map(c => (
                <button
                  key={c.id}
                  onClick={() => {
                    setSelectedCustomerId(c.id);
                    setError(null);
                  }}
                  className="suggestion-btn"
                  style={{ 
                    textAlign: 'left', 
                    fontWeight: selectedCustomerId === c.id ? 'bold' : 'normal',
                    color: selectedCustomerId === c.id ? 'var(--text-primary)' : 'var(--accent-blue)',
                    textDecoration: 'none',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                  }}
                >
                  <span>{c.id} — {c.name}</span>
                  <span className={`risk-badge ${getRiskClass(c.risk_rating)}`} style={{ transform: 'scale(0.85)', transformOrigin: 'right' }}>
                    {c.risk_rating}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {customer && (
            <div className="profile-card">
              <h3 className="suggestions-title" style={{ marginBottom: '12px' }}>KYC Profile details</h3>
              <div className="profile-field">
                <span className="profile-field-key">Entity ID</span>
                <span className="profile-field-val mono-cell">{customer.id}</span>
              </div>
              <div className="profile-field">
                <span className="profile-field-key">Legal Name</span>
                <span className="profile-field-val">{customer.name} <em style={{ color: 'var(--text-muted)', fontSize: 11 }}>(runtime id; no display name stored)</em></span>
              </div>
              <div className="profile-field">
                <span className="profile-field-key">Country</span>
                <span className="profile-field-val mono-cell">{customer.country || '—'}</span>
              </div>
              <div className="profile-field">
                <span className="profile-field-key">Segment</span>
                <span className="profile-field-val">{customer.segment || '—'}</span>
              </div>
              <div className="profile-field">
                <span className="profile-field-key">Occupation</span>
                <span className="profile-field-val">{customer.kyc_occupation || '—'}</span>
              </div>
              <div className="profile-field">
                <span className="profile-field-key">Declared Income</span>
                <span className="profile-field-val mono-cell">{customer.kyc_income_usd || '—'}</span>
              </div>
              <div className="profile-field">
                <span className="profile-field-key">KYC Risk Rating</span>
                <span className="profile-field-val">
                  <span className={`risk-badge ${getRiskClass(customer.risk_rating)}`}>
                    {customer.risk_rating}
                  </span>
                </span>
              </div>
              <div className="profile-field">
                <span className="profile-field-key">KYC Score</span>
                <span className="profile-field-val mono-cell">{customer.kyc_risk_score ?? '—'}</span>
              </div>
              <div className="profile-field">
                <span className="profile-field-key">Account Status</span>
                <span className="profile-field-val mono-cell" style={{ textTransform: 'uppercase' }}>{customer.status}</span>
              </div>
            </div>
          )}
        </div>

        {/* Right Side: Activity details */}
        <div>
          {customer ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div className="summary-panel" style={{ background: '#fff' }}>
                <div className="summary-header">Recent Transactions</div>
                <div className="table-container" style={{ border: 'none' }}>
                  <table className="console-table">
                    <thead>
                      <tr>
                        <th>Transaction ID</th>
                        <th>Amount</th>
                        <th>Currency</th>
                        <th>Date</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {customer.recent_transactions && customer.recent_transactions.length > 0 ? (
                        customer.recent_transactions.map(tx => (
                          <tr key={tx.id}>
                            <td className="mono-cell">{tx.id}</td>
                            <td className="mono-cell">{tx.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                            <td className="mono-cell">{tx.currency}</td>
                            <td className="mono-cell">{tx.date.replace('T', ' ').substring(0, 19)}Z</td>
                            <td className="mono-cell" style={{ color: tx.status === 'completed' ? '#16a34a' : '#dc2626' }}>{tx.status}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No transactions recorded.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="summary-panel" style={{ background: '#fff' }}>
                <div className="summary-header">Related Security Alerts</div>
                <div className="table-container" style={{ border: 'none' }}>
                  <table className="console-table">
                    <thead>
                      <tr>
                        <th>Alert ID</th>
                        <th>Date</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {customer.alerts && customer.alerts.length > 0 ? (
                        customer.alerts.map(a => (
                          <tr key={a.id}>
                            <td className="mono-cell">{a.id}</td>
                            <td className="mono-cell">{a.date}</td>
                            <td>
                              <span className="mono-cell" style={{ 
                                textTransform: 'uppercase', 
                                fontWeight: '600',
                                fontSize: '11px',
                                color: a.status === 'open' ? 'var(--risk-high-text)' : a.status === 'in_review' ? 'var(--risk-med-text)' : 'var(--text-muted)'
                              }}>
                                {a.status}
                              </span>
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={3} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No alerts generated for this customer.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          ) : (
            <div className="empty-state">Select a customer from the directory or search to view profiles.</div>
          )}
        </div>
      </div>
    </div>
  );
};
