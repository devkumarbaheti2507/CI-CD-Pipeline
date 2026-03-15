import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import { useApp } from '../context/AppContext';

const SERVICES = [
  { key: 'controller',   label: 'Pipeline Controller', port: 9000 },
  { key: 'analyzer',     label: 'Log Analyzer',        port: 5001 },
  { key: 'classifier',   label: 'Failure Classifier',  port: 8000 },
  { key: 'recovery',     label: 'Recovery Manager',    port: 6000 },
  { key: 'notification', label: 'Notification',        port: 7000 },
];

function severityBadge(s) {
  if (!s || s === 'NONE') return <span className="badge badge-neutral">{s || '—'}</span>;
  if (s === 'CRITICAL')   return <span className="badge badge-red">{s}</span>;
  if (s === 'HIGH')       return <span className="badge badge-yellow">{s}</span>;
  if (s === 'MEDIUM')     return <span className="badge badge-purple">{s}</span>;
  return <span className="badge badge-green">{s}</span>;
}

function statusBadge(s) {
  if (s === 'SUCCESS') return <span className="badge badge-green">SUCCESS</span>;
  if (s === 'FAILED')  return <span className="badge badge-red">FAILED</span>;
  return <span className="badge badge-neutral">{s}</span>;
}

function recoveryBadge(r) {
  if (!r || r === 'NONE') return <span className="badge badge-neutral">—</span>;
  if (r === 'ROLLBACK')   return <span className="badge badge-red">{r}</span>;
  if (r === 'RETRY')      return <span className="badge badge-cyan">{r}</span>;
  if (r === 'MANUAL')     return <span className="badge badge-yellow">{r}</span>;
  if (r === 'RESTART')    return <span className="badge badge-purple">{r}</span>;
  return <span className="badge badge-accent">{r}</span>;
}

export default function Dashboard() {
  const { events, clearEvents } = useApp();
  const [health,    setHealth]    = useState({});
  const [checking,  setChecking]  = useState(true);
  const [lastCheck, setLastCheck] = useState(null);

  const doHealthCheck = useCallback(async () => {
    setChecking(true);
    const results = {};
    await Promise.allSettled(
      SERVICES.map(async s => {
        try {
          const data = await api.health[s.key]();
          results[s.key] = { ok: true, data };
        } catch {
          results[s.key] = { ok: false, data: null };
        }
      })
    );
    setHealth(results);
    setChecking(false);
    setLastCheck(new Date().toLocaleTimeString());
  }, []);

  useEffect(() => {
    doHealthCheck();
    const t = setInterval(doHealthCheck, 15000);
    return () => clearInterval(t);
  }, [doHealthCheck]);

  const upCount   = SERVICES.filter(s => health[s.key]?.ok).length;
  const successCount = events.filter(e => e.status === 'SUCCESS').length;
  const failCount    = events.filter(e => e.status === 'FAILED').length;
  const recoveryCount = events.filter(e => e.recovery_triggered).length;

  return (
    <div>
      <div className="page-header">
        <h1>Dashboard</h1>
        <p>Live overview of all services and pipeline activity</p>
      </div>

      {/* stat row */}
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-value" style={{ color: upCount === 5 ? 'var(--green)' : 'var(--red)' }}>
            {upCount}<span style={{ fontSize: 16, color: 'var(--text3)' }}>/5</span>
          </div>
          <div className="stat-label">Services Online</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: 'var(--green)' }}>{successCount}</div>
          <div className="stat-label">Successful Pipelines</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: 'var(--red)' }}>{failCount}</div>
          <div className="stat-label">Failed Pipelines</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ color: 'var(--accent)' }}>{recoveryCount}</div>
          <div className="stat-label">Auto Recoveries</div>
        </div>
      </div>

      {/* service health */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div className="card-title" style={{ marginBottom: 0 }}>Service Health</div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {lastCheck && <span style={{ fontSize: 11, color: 'var(--text3)' }}>Last: {lastCheck}</span>}
            <button className="btn btn-ghost btn-sm" onClick={doHealthCheck}>
              {checking ? <span className="spinner" /> : '↻'} Refresh
            </button>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
          {SERVICES.map(s => {
            const h = health[s.key];
            const state = checking ? 'yellow' : h?.ok ? 'green' : 'red';
            return (
              <div key={s.key} style={{
                background: 'var(--bg2)', border: `1px solid var(--border)`,
                borderTop: `2px solid var(--${state})`, borderRadius: 'var(--r)',
                padding: '14px 14px 12px',
              }}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>{s.label}</div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>:{s.port}</span>
                  <div className={`dot dot-${state}`} />
                </div>
                {h?.data?.dependencies && (
                  <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {Object.entries(h.data.dependencies).map(([k, v]) => (
                      <span key={k} className={`badge ${v ? 'badge-green' : 'badge-red'}`} style={{ fontSize: 10 }}>
                        {k}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* recent events */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div className="card-title" style={{ marginBottom: 0 }}>Recent Pipeline Events</div>
          {events.length > 0 && (
            <button className="btn btn-ghost btn-sm" onClick={clearEvents}>Clear</button>
          )}
        </div>
        {events.length === 0 ? (
          <div className="empty">No pipeline events yet — trigger one to see activity here</div>
        ) : (
          <div className="table-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Pipeline</th>
                  <th>Status</th>
                  <th>Failure Type</th>
                  <th>Severity</th>
                  <th>Recovery</th>
                  <th>Branch</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={i}>
                    <td style={{ fontFamily: 'var(--mono)', fontWeight: 600 }}>{e.pipeline_id}</td>
                    <td>{statusBadge(e.status)}</td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text2)' }}>
                      {e.failure_type || '—'}
                    </td>
                    <td>{severityBadge(e.severity)}</td>
                    <td>{recoveryBadge(e.recovery)}</td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{e.branch || '—'}</td>
                    <td style={{ color: 'var(--text3)', fontSize: 11, fontFamily: 'var(--mono)' }}>{e.time}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
