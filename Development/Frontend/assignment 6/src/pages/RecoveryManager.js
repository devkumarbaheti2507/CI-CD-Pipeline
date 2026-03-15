import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { useApp } from '../context/AppContext';

const FAILURE_TYPES = ['BUILD_ERROR','TEST_FAILURE','DEPLOY_ERROR','DEPENDENCY_ERROR','TIMEOUT','CONFIG_ERROR','UNKNOWN'];

export default function RecoveryManager() {
  const { toast, addEvent } = useApp();
  const [form, setForm] = useState({
    pipeline_id: 'my-app', failure_type: 'BUILD_ERROR',
    run_number: '1', branch: 'main', attempt: '1',
  });
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState(null);
  const [rules,   setRules]   = useState(null);
  const [healthData, setHealthData] = useState(null);

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }

  useEffect(() => {
    api.getRecoveryRules().then(setRules).catch(() => {});
    api.health.recovery().then(setHealthData).catch(() => {});
  }, []);

  async function handleRecover() {
    setLoading(true);
    setResult(null);
    try {
      const payload = {
        pipeline_id:  form.pipeline_id,
        failure_type: form.failure_type,
        run_number:   parseInt(form.run_number, 10) || null,
        branch:       form.branch || null,
        attempt:      parseInt(form.attempt, 10) || 1,
      };
      const data = await api.recover(payload);
      setResult(data);
      toast(`Recovery: ${data.action_taken} — ${data.success ? 'success' : 'failed'}`, data.success ? 'ok' : 'error');
      addEvent({
        pipeline_id: form.pipeline_id,
        status:      'FAILED',
        failure_type: form.failure_type,
        branch:      form.branch,
        recovery:    data.action_taken,
        recovery_triggered: data.success,
      });
    } catch (err) {
      toast(err.message, 'error');
    }
    setLoading(false);
  }

  function actionColor(a) {
    const m = { ROLLBACK: 'var(--red)', MANUAL: 'var(--yellow)', RETRY: 'var(--cyan)', RESTART: 'var(--purple)', ALERT_ONLY: 'var(--accent)', SKIP: 'var(--green)' };
    return m[a] || 'var(--text2)';
  }

  return (
    <div>
      <div className="page-header">
        <h1>Recovery Manager</h1>
        <p>Manually trigger recovery actions — calls Jenkins REST API to retry, rollback, or restart</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '400px 1fr', gap: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card">
            <div className="card-title">Recovery Request</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

              <div className="form-group">
                <label className="form-label">Pipeline ID</label>
                <input className="form-input" value={form.pipeline_id}
                  onChange={e => set('pipeline_id', e.target.value)} />
              </div>

              <div className="form-group">
                <label className="form-label">Failure Type</label>
                <select className="form-select" value={form.failure_type}
                  onChange={e => set('failure_type', e.target.value)}>
                  {FAILURE_TYPES.map(f => <option key={f}>{f}</option>)}
                </select>
              </div>

              <div className="form-row cols-2">
                <div className="form-group">
                  <label className="form-label">Run Number</label>
                  <input className="form-input" type="number" min="1" value={form.run_number}
                    onChange={e => set('run_number', e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Attempt #</label>
                  <input className="form-input" type="number" min="1" value={form.attempt}
                    onChange={e => set('attempt', e.target.value)} />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Branch</label>
                <input className="form-input" value={form.branch}
                  onChange={e => set('branch', e.target.value)} />
              </div>

              <button className="btn btn-primary" style={{ justifyContent: 'center' }}
                onClick={handleRecover} disabled={loading}>
                {loading ? <><span className="spinner" /> Executing...</> : '↺  Execute Recovery'}
              </button>
            </div>
          </div>

          {/* Jenkins status */}
          <div className="card">
            <div className="card-title">Jenkins Status</div>
            {healthData ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 13 }}>Jenkins</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div className={`dot ${healthData.jenkins ? 'dot-green' : 'dot-red'}`} />
                    <span style={{ fontSize: 12, color: healthData.jenkins ? 'var(--green)' : 'var(--red)' }}>
                      {healthData.jenkins ? 'connected' : 'unreachable'}
                    </span>
                  </div>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'var(--mono)' }}>
                  {healthData.jenkins_url}
                </div>
              </div>
            ) : (
              <div className="empty" style={{ padding: '12px 0' }}>Loading...</div>
            )}
          </div>
        </div>

        {/* Result + Rules */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {result ? (
            <div className="card">
              <div className="card-title">Recovery Result</div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 14 }}>
                <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: '16px 20px', textAlign: 'center', minWidth: 140 }}>
                  <div style={{ fontSize: 26, fontWeight: 700, fontFamily: 'var(--mono)', color: actionColor(result.action_taken) }}>
                    {result.action_taken}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 6 }}>ACTION TAKEN</div>
                </div>
                <div style={{ background: 'var(--bg2)', border: `1px solid ${result.success ? 'rgba(62,207,142,.3)' : 'rgba(244,91,105,.3)'}`, borderRadius: 'var(--r)', padding: '16px 20px', textAlign: 'center', minWidth: 120 }}>
                  <div style={{ fontSize: 26, fontWeight: 700, color: result.success ? 'var(--green)' : 'var(--red)' }}>
                    {result.success ? '✓' : '✗'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 6 }}>{result.success ? 'SUCCESS' : 'FAILED'}</div>
                </div>
              </div>
              <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: '10px 14px', fontSize: 13, color: 'var(--text2)' }}>
                {result.message}
              </div>
            </div>
          ) : (
            <div className="card"><div className="empty">Execute a recovery to see the result</div></div>
          )}

          {rules && (
            <div className="card">
              <div className="card-title">Recovery Rules</div>
              <div className="table-wrap">
                <table className="tbl">
                  <thead><tr><th>Failure Type</th><th>Default Action</th></tr></thead>
                  <tbody>
                    {Object.entries(rules.rules || {}).map(([ft, action]) => (
                      <tr key={ft}>
                        <td><span className="badge badge-yellow">{ft}</span></td>
                        <td>
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: actionColor(action.split(' ')[0]) }}>
                            {action}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
