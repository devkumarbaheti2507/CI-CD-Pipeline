// ── Base URLs — change these if your services run on different hosts/ports ──
const URLS = {
  controller:   process.env.REACT_APP_CONTROLLER_URL   || 'http://localhost:9000',
  analyzer:     process.env.REACT_APP_ANALYZER_URL     || 'http://localhost:5001',
  classifier:   process.env.REACT_APP_CLASSIFIER_URL   || 'http://localhost:8000',
  recovery:     process.env.REACT_APP_RECOVERY_URL     || 'http://localhost:6001',
  notification: process.env.REACT_APP_NOTIFICATION_URL || 'http://localhost:7000',
};

async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  let data;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    const msg = data?.detail || data?.message || `HTTP ${res.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

// ── Pipeline Controller ────────────────────────────────────────
export const api = {
  // Health checks
  health: {
    controller:   () => request(`${URLS.controller}/health`),
    analyzer:     () => request(`${URLS.analyzer}/api/v1/health`),
    classifier:   () => request(`${URLS.classifier}/health`),
    recovery:     () => request(`${URLS.recovery}/health`),
    notification: () => request(`${URLS.notification}/health`),
  },

  // Pipeline Controller
  triggerPipeline: (payload, apiKey) =>
    request(`${URLS.controller}/pipeline-event`, {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json', ...(apiKey ? { 'X-API-Key': apiKey } : {}) },
    }),

  getJobStatus: (jobId, apiKey) =>
    request(`${URLS.controller}/pipeline-status/${jobId}`, {
      headers: { 'Content-Type': 'application/json', ...(apiKey ? { 'X-API-Key': apiKey } : {}) },
    }),

  // Log Analyzer
  analyzeLogs: (log, source = 'dashboard') =>
    request(`${URLS.analyzer}/api/v1/analyze`, {
      method: 'POST',
      body: JSON.stringify({ log, source }),
    }),

  getAnalyzerRules: () => request(`${URLS.analyzer}/api/v1/rules`),
  getAnalyzerMetrics: () => request(`${URLS.analyzer}/api/v1/metrics`),

  // Failure Classifier
  classify: (payload) =>
    request(`${URLS.classifier}/classify`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getClassifyRules: () => request(`${URLS.classifier}/classify/rules`),

  // Recovery Manager
  recover: (payload) =>
    request(`${URLS.recovery}/recover`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getRecoveryRules: () => request(`${URLS.recovery}/recover/rules`),

  // Notification Service
  notify: (payload) =>
    request(`${URLS.notification}/notify`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
