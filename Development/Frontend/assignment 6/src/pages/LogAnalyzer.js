import React, { useState } from 'react';
import { api } from '../api';
import { useApp } from '../context/AppContext';

const SAMPLES = {
  'Build Error': `[Pipeline] Starting build for my-app
[INFO] Compiling source files...
ERROR: Cannot find module 'express'
npm ERR! code ENOENT
npm ERR! errno -2
npm ERR! syscall open
npm ERR! exit status 1
Build FAILED at stage: npm install`,

  'Test Failure': `Running test suite with Jest...
PASS  src/utils.test.js (1.2s)
FAIL  src/auth.test.js
  ● AuthService › login › should validate credentials
    Expected: 200
    Received: 401
    at Object.toEqual (src/auth.test.js:23:32)
Tests: 2 failed, 18 passed
Test suite FAILED`,

  'Deploy Error': `Deploying my-app to production cluster...
kubectl apply -f k8s/deployment.yaml
Waiting for rollout to complete...
Error from server: pods "my-app-7d9f8b" is forbidden
ImagePullBackOff: Back-off pulling image "registry.example.com/my-app:v1.2.3"
Deployment FAILED — rolling back to previous version`,

  'Dependency Error': `[Pipeline] Downloading project dependencies
GET https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz
HTTP 401 Unauthorized
npm ERR! 401 Unauthorized
npm ERR! 401 registry.npmjs.org/lodash requires auth credentials`,

  'Config Error': `Starting application server...
ERROR: Missing environment variable: DATABASE_URL
Config validation failed: ENOENT no such file or directory '/app/.env'
Process exited with code 1`,
};

function SeverityLabel({ s }) {
  const map = { CRITICAL: 'badge-red', HIGH: 'badge-yellow', MEDIUM: 'badge-purple', LOW: 'badge-green', NONE: 'badge-neutral' };
  return <span className={`badge ${map[s] || 'badge-neutral'}`}>{s || '—'}</span>;
}
function RecoveryLabel({ r }) {
  const map = { RETRY: 'badge-cyan', ROLLBACK: 'badge-red', RESTART: 'badge-purple', MANUAL: 'badge-yellow', ALERT_ONLY: 'badge-accent', NONE: 'badge-neutral' };
  return <span className={`badge ${map[r] || 'badge-neutral'}`}>{r || '—'}</span>;
}

export default function LogAnalyzer() {
  const { toast, addEvent } = useApp();
  const [log,            setLog]            = useState('');
  const [analyzing,      setAnalyzing]      = useState(false);
  const [analysis,       setAnalysis]       = useState(null);
  const [classifying,    setClassifying]    = useState(false);
  const [classification, setClassification] = useState(null);
  const [pipeline,       setPipeline]       = useState('my-app');
  const [branch,         setBranch]         = useState('main');
  const [attempt,        setAttempt]        = useState('1');
  const [stage,          setStage]          = useState('build');

  async function handleAnalyze() {
    if (!log.trim()) { toast('Paste a log first', 'error'); return; }
    setAnalyzing(true);
    setAnalysis(null);
    setClassification(null);
    try {
      const data = await api.analyzeLogs(log);
      setAnalysis(data);
      toast('Log analyzed successfully', 'ok');
    } catch (err) {
      toast(err.message, 'error');
    }
    setAnalyzing(false);
  }

  async function handleClassify() {
    if (!analysis) return;
    setClassifying(true);
    setClassification(null);
    try {
      const payload = {
        pipeline_id: pipeline,
        stage,
        attempt:     parseInt(attempt, 10) || 1,
        branch,
        analysis: {
          status:         analysis.status,
          failure_type:   analysis.failure_category,
          failures_found: analysis.failures_found || 0,
          details:        analysis.findings || [],
        },
      };
      const data = await api.classify(payload);
      setClassification(data);
      toast('Failure classified', 'ok');
      addEvent({
        pipeline_id:       pipeline,
        status:            analysis.status,
        failure_type:      data.failure_type,
        severity:          data.severity,
        recovery:          data.recovery,
        branch,
        recovery_triggered: false,
      });
    } catch (err) {
      toast(err.message, 'error');
    }
    setClassifying(false);
  }

  return (
    <div>
      <div className="page-header">
        <h1>Log Analyzer</h1>
        <p>Paste a Jenkins build log → analyze failure → classify severity and recovery action</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Input */}
        <div className="card">
          <div className="card-title">Log Input</div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
            {Object.keys(SAMPLES).map(name => (
              <button key={name} className="tag" onClick={() => setLog(SAMPLES[name])}>{name}</button>
            ))}
          </div>

          <textarea className="form-textarea" style={{ minHeight: 200 }}
            placeholder="Paste Jenkins build log here..."
            value={log} onChange={e => setLog(e.target.value)} />

          <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 10 }}>
            <div className="form-group">
              <label className="form-label">Pipeline</label>
              <input className="form-input" value={pipeline} onChange={e => setPipeline(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Branch</label>
              <input className="form-input" value={branch} onChange={e => setBranch(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Stage</label>
              <select className="form-select" value={stage} onChange={e => setStage(e.target.value)}>
                {['build','test','deploy','install'].map(s => <option key={s}>{s}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Attempt</label>
              <input className="form-input" type="number" min="1" value={attempt}
                onChange={e => setAttempt(e.target.value)} />
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
            <button className="btn btn-primary" style={{ flex: 1, justifyContent: 'center' }}
              onClick={handleAnalyze} disabled={analyzing || !log.trim()}>
              {analyzing ? <><span className="spinner" /> Analyzing...</> : '⌕  Analyze Log'}
            </button>
            <button className="btn btn-ghost" style={{ flex: 1, justifyContent: 'center' }}
              onClick={handleClassify} disabled={classifying || !analysis}>
              {classifying ? <><span className="spinner" /> Classifying...</> : '⚡  Classify Failure'}
            </button>
          </div>
        </div>

        {/* Results */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Analysis result */}
          {analysis ? (
            <div className="card">
              <div className="card-title">Analysis Result</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>Status</div>
                  <span className={`badge ${analysis.status === 'FAILED' ? 'badge-red' : 'badge-green'}`}>
                    {analysis.status}
                  </span>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>Failure Category</div>
                  <span className="badge badge-yellow">{analysis.failure_category || 'unknown'}</span>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>Severity</div>
                  <SeverityLabel s={analysis.overall_severity} />
                </div>
                {analysis.confidence_score != null && (
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>Confidence</div>
                    <span style={{ fontWeight: 700, color: 'var(--accent)', fontFamily: 'var(--mono)' }}>
                      {Math.round(analysis.confidence_score * 100)}%
                    </span>
                  </div>
                )}
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>Lines</div>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>{analysis.total_lines || '—'}</span>
                </div>
              </div>

              {/* confidence bar */}
              {analysis.confidence_score != null && (
                <div style={{ marginBottom: 14 }}>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${analysis.confidence_score * 100}%` }} />
                  </div>
                </div>
              )}

              {/* findings */}
              {analysis.findings?.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 8 }}>Findings ({analysis.findings.length})</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto' }}>
                    {analysis.findings.slice(0, 6).map((f, i) => (
                      <div key={i} style={{
                        background: 'var(--bg2)', border: '1px solid var(--border)',
                        borderRadius: 6, padding: '7px 12px', fontSize: 12,
                      }}>
                        {f.category && <span className="badge badge-yellow" style={{ marginRight: 8, fontSize: 10 }}>{f.category}</span>}
                        <span style={{ color: 'var(--text2)' }}>{f.content || f.message || JSON.stringify(f)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="card"><div className="empty">Analyze a log to see results</div></div>
          )}

          {/* Classification result */}
          {classification ? (
            <div className="card">
              <div className="card-title">Classification Result</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14, marginBottom: 14 }}>
                <div style={{ textAlign: 'center', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: '14px 10px' }}>
                  <SeverityLabel s={classification.severity} />
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 6 }}>Severity</div>
                </div>
                <div style={{ textAlign: 'center', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: '14px 10px' }}>
                  <RecoveryLabel r={classification.recovery} />
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 6 }}>Recovery Action</div>
                </div>
                <div style={{ textAlign: 'center', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: '14px 10px' }}>
                  <span className={`badge ${classification.is_production ? 'badge-red' : 'badge-green'}`}>
                    {classification.is_production ? 'PRODUCTION' : 'DEV'}
                  </span>
                  <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 6 }}>Environment</div>
                </div>
              </div>
              <div style={{
                background: 'var(--bg2)', border: '1px solid var(--border)',
                borderRadius: 'var(--r)', padding: '10px 14px',
                fontSize: 13, color: 'var(--text2)', lineHeight: 1.6,
              }}>
                {classification.reason}
              </div>
              {classification.escalated && (
                <div style={{ marginTop: 10 }}>
                  <span className="badge badge-red">⚠ ESCALATED — manual intervention required</span>
                </div>
              )}
            </div>
          ) : analysis ? (
            <div className="card" style={{ background: 'var(--accent-glow)', border: '1px solid var(--accent)', opacity: .7 }}>
              <div style={{ fontSize: 13, color: 'var(--accent)', textAlign: 'center' }}>
                Click "Classify Failure" to get severity and recovery recommendation
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
