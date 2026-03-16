import React, { useState, useRef } from 'react';
import { api } from '../api';
import { useApp } from '../context/AppContext';

const FAILURE_TYPES = ['BUILD_ERROR','TEST_FAILURE','DEPLOY_ERROR','DEPENDENCY_ERROR','TIMEOUT','CONFIG_ERROR','UNKNOWN'];

function genId() { return 'evt-' + Math.random().toString(36).slice(2, 11); }

export default function TriggerPipeline() {
  const { toast, addEvent } = useApp();
  const [apiKey,   setApiKey]   = useState(localStorage.getItem('cicd_apikey') || '');
  const [form,     setForm]     = useState({
    event_id:    genId(),
    pipeline_id: 'my-app',
    run_number:  '1',
    status:      'FAILED',
    log_url:     'http://localhost:8080/job/my-app/1/consoleText',
    branch:      'main',
  });
  const [loading,   setLoading]   = useState(false);
  const [response,  setResponse]  = useState(null);
  const [jobId,     setJobId]     = useState('');
  const [jobStatus, setJobStatus] = useState(null);
  const [polling,   setPolling]   = useState(false);
  const pollRef = useRef(null);

  function set(k, v) { setForm(f => ({ ...f, [k]: v })); }

  function saveApiKey(v) {
    setApiKey(v);
    localStorage.setItem('cicd_apikey', v);
  }

  async function handleTrigger() {
    if (!form.event_id || !form.pipeline_id || !form.log_url) {
      toast('Fill in Event ID, Pipeline ID, and Log URL', 'error');
      return;
    }
    setLoading(true);
    setResponse(null);
    setJobStatus(null);
    if (pollRef.current) clearInterval(pollRef.current);

    const payload = {
      event_id:    form.event_id,
      pipeline_id: form.pipeline_id,
      run_number:  parseInt(form.run_number, 10) || 1,
      status:      form.status,
      log_url:     form.log_url,
    };

    try {
      const data = await api.triggerPipeline(payload, apiKey);
      setResponse({ ok: true, data });
      toast('Pipeline event accepted', 'ok');

      addEvent({
        pipeline_id: form.pipeline_id,
        status:      form.status,
        branch:      form.branch,
        failure_type: null, severity: null, recovery: null,
        recovery_triggered: false,
      });

      if (data.job_id) {
        setJobId(data.job_id);
        setPolling(true);
        let attempts = 0;
        pollRef.current = setInterval(async () => {
          try {
            const s = await api.getJobStatus(data.job_id, apiKey);
            setJobStatus(s);
            if (++attempts >= 12 || s.status === 'completed') {
              clearInterval(pollRef.current);
              setPolling(false);
            }
          } catch {
            if (++attempts >= 12) { clearInterval(pollRef.current); setPolling(false); }
          }
        }, 2500);
      }
    } catch (err) {
      setResponse({ ok: false, error: err.message });
      toast(err.message, 'error');
    }
    setLoading(false);
    set('event_id', genId());
  }

  return (
    <div>
      <div className="page-header">
        <h1>Trigger Pipeline</h1>
        <p>Send a pipeline event to the controller — simulates a GitHub webhook push</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Form */}
        <div className="card">
          <div className="card-title">Event Payload</div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <div className="form-group" style={{ flex: 1 }}>
                <label className="form-label">Event ID</label>
                <input className="form-input" value={form.event_id}
                  onChange={e => set('event_id', e.target.value)} placeholder="auto-generated" />
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                <button className="btn btn-ghost btn-sm" onClick={() => set('event_id', genId())}>↻ New</button>
              </div>
            </div>

            <div className="form-row cols-2">
              <div className="form-group">
                <label className="form-label">Pipeline ID</label>
                <input className="form-input" value={form.pipeline_id}
                  onChange={e => set('pipeline_id', e.target.value)} placeholder="must match Jenkins job name" />
              </div>
              <div className="form-group">
                <label className="form-label">Branch</label>
                <input className="form-input" value={form.branch}
                  onChange={e => set('branch', e.target.value)} placeholder="main" />
              </div>
            </div>

            <div className="form-row cols-2">
              <div className="form-group">
                <label className="form-label">Status</label>
                <select className="form-select" value={form.status} onChange={e => set('status', e.target.value)}>
                  <option>FAILED</option>
                  <option>SUCCESS</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Run Number</label>
                <input className="form-input" type="number" min="1" value={form.run_number}
                  onChange={e => set('run_number', e.target.value)} />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Jenkins Log URL</label>
              <input className="form-input" value={form.log_url}
                onChange={e => set('log_url', e.target.value)}
                placeholder="http://localhost:8080/job/my-app/1/consoleText" />
            </div>

            <div className="divider" style={{ margin: '4px 0' }} />

            <div className="form-group">
              <label className="form-label">X-API-Key (STATUS_API_KEY from .env)</label>
              <input className="form-input" type="password" value={apiKey}
                onChange={e => saveApiKey(e.target.value)} placeholder="optional — leave blank if not set" />
            </div>

            <button className="btn btn-primary" onClick={handleTrigger}
              disabled={loading} style={{ justifyContent: 'center', marginTop: 4 }}>
              {loading ? <><span className="spinner" /> Sending...</> : '▶  Trigger Pipeline Event'}
            </button>
          </div>
        </div>

        {/* Response + job status */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card">
            <div className="card-title">Response</div>
            {!response
              ? <div className="empty">Response will appear here</div>
              : response.ok
                ? <div className="code-block">{JSON.stringify(response.data, null, 2)}</div>
                : <div className="code-block error">{response.error}</div>
            }
          </div>

          {jobId && (
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <div className="card-title" style={{ marginBottom: 0 }}>Job Status</div>
                {polling && (
                  <span style={{ fontSize: 11, color: 'var(--yellow)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className="dot dot-yellow" style={{ width: 6, height: 6 }} /> polling...
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 10, fontFamily: 'var(--mono)' }}>
                job_id: <span style={{ color: 'var(--accent)' }}>{jobId}</span>
              </div>
              {jobStatus
                ? <div className="code-block">{JSON.stringify(jobStatus, null, 2)}</div>
                : <div style={{ display: 'flex', gap: 8, color: 'var(--text3)', fontSize: 13, alignItems: 'center' }}>
                    <span className="spinner" /> Waiting for job status...
                  </div>
              }
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
