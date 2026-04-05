import React, { useState } from 'react';

const DEFAULTS = {
  REACT_APP_CONTROLLER_URL:   'http://localhost:9000',
  REACT_APP_ANALYZER_URL:     'http://localhost:5001',
  REACT_APP_CLASSIFIER_URL:   'http://localhost:8000',
  REACT_APP_RECOVERY_URL:     'http://localhost:6000',
  REACT_APP_NOTIFICATION_URL: 'http://localhost:7000',
};

const KEY_LABELS = {
  REACT_APP_CONTROLLER_URL:   'Pipeline Controller URL',
  REACT_APP_ANALYZER_URL:     'Log Analyzer URL',
  REACT_APP_CLASSIFIER_URL:   'Failure Classifier URL',
  REACT_APP_RECOVERY_URL:     'Recovery Manager URL',
  REACT_APP_NOTIFICATION_URL: 'Notification Service URL',
};

const CORS_SNIPPET = `from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)`;

const ENV_SNIPPET = Object.entries(DEFAULTS)
  .map(([k, v]) => `${k}=${v}`)
  .join('\n');

export default function Settings() {
  const [copied, setCopied] = useState('');

  function copy(text, key) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(''), 1500);
    });
  }

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>Service URLs, CORS setup, and environment configuration</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Service URLs */}
        <div className="card">
          <div className="card-title">Service URLs</div>
          <p style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 14, lineHeight: 1.6 }}>
            These are read from environment variables at build time. To change them, update your
            <span className="mono" style={{ color: 'var(--accent)' }}> .env</span> file and restart the dev server.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {Object.entries(DEFAULTS).map(([key, val]) => (
              <div key={key}>
                <div className="form-label" style={{ marginBottom: 4 }}>{KEY_LABELS[key]}</div>
                <div style={{
                  display: 'flex', gap: 8, alignItems: 'center',
                  background: 'var(--bg2)', border: '1px solid var(--border)',
                  borderRadius: 'var(--r)', padding: '7px 12px',
                  fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--accent)',
                }}>
                  <span style={{ flex: 1 }}>{process.env[key] || val}</span>
                  <span className="badge badge-neutral" style={{ fontSize: 10 }}>default</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* .env template */}
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div className="card-title" style={{ marginBottom: 0 }}>.env File Template</div>
              <button className="btn btn-ghost btn-sm" onClick={() => copy(ENV_SNIPPET, 'env')}>
                {copied === 'env' ? '✓ Copied' : 'Copy'}
              </button>
            </div>
            <div className="code-block neutral">{ENV_SNIPPET}</div>
            <p style={{ fontSize: 12, color: 'var(--text3)', marginTop: 10 }}>
              Place this in <span className="mono">cicd-dashboard/.env</span> and restart with <span className="mono">npm start</span>
            </p>
          </div>

          {/* CORS */}
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div className="card-title" style={{ marginBottom: 0 }}>CORS — Add to Every Python Service</div>
              <button className="btn btn-ghost btn-sm" onClick={() => copy(CORS_SNIPPET, 'cors')}>
                {copied === 'cors' ? '✓ Copied' : 'Copy'}
              </button>
            </div>
            <div className="code-block neutral">{CORS_SNIPPET}</div>
            <p style={{ fontSize: 12, color: 'var(--text3)', marginTop: 10 }}>
              Add after <span className="mono">app = FastAPI(...)</span> in all 4 FastAPI services.
              Then: <span className="mono">pip install fastapi[all]</span>
            </p>
          </div>
        </div>
      </div>

      {/* Quick start */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">How to Run</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {[
            { step: '1', title: 'Start backend services', code: 'python log_analyzer.py\nuvicorn failure_classifier:app --port 8000\nuvicorn recovery_manager:app --port 6000\nuvicorn notification_service:app --port 7000\nuvicorn pipeline_controller:app --port 9000' },
            { step: '2', title: 'Install and run UI', code: 'cd cicd-dashboard\nnpm install\nnpm start\n\n# Opens at http://localhost:3000' },
            { step: '3', title: 'Build for production', code: 'npm run build\n\n# Outputs to cicd-dashboard/build/\n# Serve with any static file server\n# e.g: npx serve -s build' },
          ].map(({ step, title, code }) => (
            <div key={step} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', padding: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <div style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--accent)', color: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>{step}</div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
              </div>
              <pre style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text2)', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{code}</pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
