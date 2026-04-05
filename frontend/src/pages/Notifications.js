import React, { useState } from 'react';
import { api } from '../api';
import { useApp } from '../context/AppContext';

const FAILURE_TYPES = ['BUILD_ERROR','TEST_FAILURE','DEPLOY_ERROR','DEPENDENCY_ERROR','TIMEOUT','CONFIG_ERROR','UNKNOWN'];

function getHistory() {
  try { return JSON.parse(localStorage.getItem('cicd_notifications') || '[]'); }
  catch { return []; }
}

export default function Notifications() {
  const { toast } = useApp();
  const [form, setForm] = useState({
    pipeline_id: 'my-app', status: 'FAILED',
    failure_type: 'BUILD_ERROR', recovery_triggered: false,
  });
  const [sending, setSending] = useState(false);
  const [result,  setResult]  = useState(null);
  const [history, setHistory] = useState(getHistory);

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }

  async function handleSend() {
    setSending(true);
    setResult(null);
    try {
      const payload = {
        pipeline_id:        form.pipeline_id,
        status:             form.status,
        failure_type:       form.status === 'SUCCESS' ? null : form.failure_type,
        recovery_triggered: form.recovery_triggered,
      };
      const data = await api.notify(payload);
      setResult({ ok: true, data });

      const item = { ...form, channels: data.channels || {}, any_sent: data.any_sent, time: new Date().toLocaleTimeString() };
      const h = [item, ...getHistory()].slice(0, 50);
      localStorage.setItem('cicd_notifications', JSON.stringify(h));
      setHistory(h);

      const sent = Object.values(data.channels || {}).filter(Boolean).length;
      toast(`Notification sent via ${sent} channel(s)`, sent > 0 ? 'ok' : 'info');
    } catch (err) {
      setResult({ ok: false, error: err.message });
      toast(err.message, 'error');
    }
    setSending(false);
  }

  function channelIcon(c) {
    return c === 'email' ? '✉' : c === 'slack' ? '💬' : c === 'webhook' ? '🔗' : '•';
  }

  return (
    <div>
      <div className="page-header">
        <h1>Notifications</h1>
        <p>Send pipeline alerts and view delivery history</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: 16 }}>
        {/* Form */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card">
            <div className="card-title">Send Notification</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="form-group">
                <label className="form-label">Pipeline ID</label>
                <input className="form-input" value={form.pipeline_id}
                  onChange={e => set('pipeline_id', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Status</label>
                <select className="form-select" value={form.status} onChange={e => set('status', e.target.value)}>
                  <option>FAILED</option><option>SUCCESS</option>
                </select>
              </div>
              {form.status === 'FAILED' && (
                <div className="form-group">
                  <label className="form-label">Failure Type</label>
                  <select className="form-select" value={form.failure_type}
                    onChange={e => set('failure_type', e.target.value)}>
                    {FAILURE_TYPES.map(f => <option key={f}>{f}</option>)}
                  </select>
                </div>
              )}
              <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', fontSize: 13 }}>
                <input type="checkbox" checked={form.recovery_triggered}
                  onChange={e => set('recovery_triggered', e.target.checked)} />
                <span style={{ color: 'var(--text2)' }}>Recovery was triggered</span>
              </label>
              <button className="btn btn-primary" style={{ justifyContent: 'center' }}
                onClick={handleSend} disabled={sending}>
                {sending ? <><span className="spinner" /> Sending...</> : '◎  Send Notification'}
              </button>
            </div>
          </div>

          {/* Channel delivery result */}
          {result && (
            <div className="card">
              <div className="card-title">Delivery Status</div>
              {result.ok ? (
                <div style={{ display: 'flex', gap: 10 }}>
                  {Object.entries(result.data?.channels || {}).map(([ch, sent]) => (
                    <div key={ch} style={{
                      flex: 1, textAlign: 'center', padding: '14px 8px',
                      background: 'var(--bg2)',
                      border: `1px solid ${sent ? 'rgba(62,207,142,.4)' : 'var(--border)'}`,
                      borderRadius: 'var(--r)',
                    }}>
                      <div style={{ fontSize: 20, marginBottom: 4 }}>{channelIcon(ch)}</div>
                      <div style={{ fontSize: 12, fontWeight: 600 }}>{ch}</div>
                      <div style={{ fontSize: 11, color: sent ? 'var(--green)' : 'var(--text3)', marginTop: 3 }}>
                        {sent ? 'delivered' : 'skipped'}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="code-block error">{result.error}</div>
              )}
            </div>
          )}
        </div>

        {/* History */}
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div className="card-title" style={{ marginBottom: 0 }}>Notification History</div>
            {history.length > 0 && (
              <button className="btn btn-ghost btn-sm" onClick={() => {
                localStorage.removeItem('cicd_notifications');
                setHistory([]);
              }}>Clear</button>
            )}
          </div>
          {history.length === 0 ? (
            <div className="empty">No notifications sent yet</div>
          ) : (
            <div className="table-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Pipeline</th>
                    <th>Status</th>
                    <th>Failure</th>
                    <th>Channels Sent</th>
                    <th>Recovery</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h, i) => (
                    <tr key={i}>
                      <td style={{ fontFamily: 'var(--mono)', fontWeight: 600 }}>{h.pipeline_id}</td>
                      <td>
                        <span className={`badge ${h.status === 'SUCCESS' ? 'badge-green' : 'badge-red'}`}>
                          {h.status}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text2)' }}>
                        {h.failure_type || '—'}
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {Object.entries(h.channels || {}).filter(([, v]) => v).map(([ch]) => (
                            <span key={ch} className="badge badge-accent" style={{ fontSize: 10 }}>{ch}</span>
                          ))}
                          {!h.any_sent && <span style={{ color: 'var(--text3)', fontSize: 12 }}>none</span>}
                        </div>
                      </td>
                      <td>
                        {h.recovery_triggered
                          ? <span className="badge badge-cyan">yes</span>
                          : <span style={{ color: 'var(--text3)', fontSize: 12 }}>no</span>}
                      </td>
                      <td style={{ color: 'var(--text3)', fontSize: 11, fontFamily: 'var(--mono)' }}>{h.time}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
