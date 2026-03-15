import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { useApp } from '../context/AppContext';

const FAILURE_TYPES = ['BUILD_ERROR','TEST_FAILURE','DEPLOY_ERROR','DEPENDENCY_ERROR','TIMEOUT','CONFIG_ERROR','UNKNOWN'];
const STAGES        = ['build','test','deploy','install','lint','package'];

export default function FailureClassifier() {
  const { toast } = useApp();
  const [form, setForm] = useState({
    pipeline_id: 'my-app', stage: 'build', attempt: '1', branch: 'main',
    failure_type: 'BUILD_ERROR', status: 'FAILED', failures_found: '1',
  });
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState(null);
  const [rules,   setRules]   = useState(null);

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }

  useEffect(() => {
    api.getClassifyRules()
      .then(setRules)
      .catch(() => {});
  }, []);

  async function handleClassify() {
    setLoading(true);
    setResult(null);
    try {
      const payload = {
        pipeline_id: form.pipeline_id,
        stage:       form.stage,
        attempt:     parseInt(form.attempt, 10) || 1,
        branch:      form.branch,
        analysis: {
          status:         form.status,
          failure_type:   form.failure_type,
          failures_found: parseInt(form.failures_found, 10) || 0,
          details:        [],
        },
      };
      const data = await api.classify(payload);
      setResult(data);
      toast('Classified successfully', 'ok');
    } catch (err) {
      toast(err.message, 'error');
    }
    setLoading(false);
  }

  function severityColor(s) {
    const m = { CRITICAL: 'var(--red)', HIGH: 'var(--yellow)', MEDIUM: 'var(--purple)', LOW: 'var(--green)', NONE: 'var(--text3)' };
    return m[s] || 'var(--text2)';
  }
  function recoveryColor(r) {
    const m = { ROLLBACK: 'var(--red)', MANUAL: 'var(--yellow)', RETRY: 'var(--cyan)', RESTART: 'var(--purple)', ALERT_ONLY: 'var(--accent)', NONE: 'var(--text3)' };
    return m[r] || 'var(--text2)';
  }

  return (
    <div>
      <div className="page-header">
        <h1>Failure Classifier</h1>
        <p>Manually classify a failure to get severity level and recommended recovery action</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '420px 1fr', gap: 16 }}>
        {/* Form */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card">
            <div className="card-title">Classify Request</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

              <div className="form-row cols-2">
                <div className="form-group">
                  <label className="form-label">Pipeline ID</label>
                  <input className="form-input" value={form.pipeline_id}
                    onChange={e => set('pipeline_id', e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Branch</label>
                  <input className="form-input" value={form.branch}
                    onChange={e => set('branch', e.target.value)} />
                </div>
              </div>

              <div className="form-row cols-2">
                <div className="form-group">
                  <label className="form-label">Stage</label>
                  <select className="form-select" value={form.stage} onChange={e => set('stage', e.target.value)}>
                    {STAGES.map(s => <option key={s}>{s}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Attempt #</label>
                  <input className="form-input" type="number" min="1" value={form.attempt}
                    onChange={e => set('attempt', e.target.value)} />
                </div>
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
                  <label className="form-label">Status</label>
                  <select className="form-select" value={form.status} onChange={e => set('status', e.target.value)}>
                    <option>FAILED</option><option>SUCCESS</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Failures Found</label>
                  <input className="form-input" type="number" min="0" value={form.failures_found}
                    onChange={e => set('failures_found', e.target.value)} />
                </div>
              </div>

              <button className="btn btn-primary" style={{ justifyContent: 'center' }}
                onClick={handleClassify} disabled={loading}>
                {loading ? <><span className="spinner" /> Classifying...</> : '⚡  Classify'}
              </button>
            </div>
          </div>

          {/* Production impact note */}
          <div style={{
            background: 'var(--red-dim)', border: '1px solid rgba(244,91,105,.3)',
            borderRadius: 'var(--r)', padding: '12px 14px', fontSize: 12, color: 'var(--text2)',
          }}>
            <strong style={{ color: 'var(--red)' }}>Production rules:</strong> DEPLOY_ERROR on
            main/master/production → ROLLBACK immediately. Attempt &gt; {2} → MANUAL.
          </div>
        </div>

        {/* Results */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {result ? (
            <div className="card">
              <div className="card-title">Result</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 16 }}>
                <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: 18, textAlign: 'center' }}>
                  <div style={{ fontSize: 28, fontWeight: 700, fontFamily: 'var(--mono)', color: severityColor(result.severity) }}>
                    {result.severity}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 6 }}>SEVERITY</div>
                </div>
                <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: 18, textAlign: 'center' }}>
                  <div style={{ fontSize: 28, fontWeight: 700, fontFamily: 'var(--mono)', color: recoveryColor(result.recovery) }}>
                    {result.recovery}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 6 }}>RECOVERY ACTION</div>
                </div>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
                <div style={{ fontSize: 13 }}>
                  <span style={{ color: 'var(--text3)' }}>Failure type: </span>
                  <span className="badge badge-yellow">{result.failure_type}</span>
                </div>
                <div style={{ fontSize: 13 }}>
                  <span style={{ color: 'var(--text3)' }}>Environment: </span>
                  <span className={`badge ${result.is_production ? 'badge-red' : 'badge-green'}`}>
                    {result.is_production ? 'PRODUCTION' : 'NON-PRODUCTION'}
                  </span>
                </div>
                {result.escalated && (
                  <span className="badge badge-red">⚠ ESCALATED</span>
                )}
              </div>

              <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: '12px 14px', fontSize: 13, color: 'var(--text2)', lineHeight: 1.6 }}>
                {result.reason}
              </div>
            </div>
          ) : (
            <div className="card"><div className="empty">Submit the form to see classification result</div></div>
          )}

          {/* Rules table */}
          {rules && (
            <div className="card">
              <div className="card-title">Classification Rules</div>
              <div className="table-wrap">
                <table className="tbl">
                  <thead><tr><th>Failure Type</th><th>Recovery Action</th></tr></thead>
                  <tbody>
                    {Object.entries(rules.rules || {}).map(([ft, action]) => (
                      <tr key={ft}>
                        <td><span className="badge badge-yellow">{ft}</span></td>
                        <td>
                          <span className="mono" style={{ fontSize: 12 }}>{action}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {rules.max_auto_retries && (
                <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text3)' }}>
                  Max auto retries: <span style={{ color: 'var(--accent)', fontFamily: 'var(--mono)' }}>{rules.max_auto_retries}</span>
                  {' '} | Production branches: <span style={{ color: 'var(--accent)', fontFamily: 'var(--mono)' }}>{(rules.production_branches || []).join(', ')}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
