import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';

const Ctx = createContext();
export const useApp = () => useContext(Ctx);

export function AppProvider({ children }) {
  const [toasts,   setToasts]   = useState([]);
  const [events,   setEvents]   = useState(() => {
    try { return JSON.parse(localStorage.getItem('cicd_events') || '[]'); }
    catch { return []; }
  });

  // ── Toast helpers ──────────────────────────────────────────
  const toast = useCallback((msg, type = 'info') => {
    const id = Date.now();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500);
  }, []);

  // ── Event log ──────────────────────────────────────────────
  const addEvent = useCallback((ev) => {
    setEvents(prev => {
      const next = [{ ...ev, time: new Date().toLocaleTimeString() }, ...prev].slice(0, 100);
      localStorage.setItem('cicd_events', JSON.stringify(next));
      return next;
    });
  }, []);

  const clearEvents = useCallback(() => {
    setEvents([]);
    localStorage.removeItem('cicd_events');
  }, []);

  useEffect(() => {
    const fetchLiveEvents = async () => {
      try {
        const { api } = require('../api');
        const live = await api.getEvents();
        if (live && live.length > 0) {
          setEvents(prev => {
            const newEvents = [...prev];
            let changed = false;
            for (const ev of live) {
              const mapped = {
                job_id: ev.job_id,
                pipeline_id: ev.pipeline_id,
                status: ev.status === 'processing' ? 'PROCESSING' : 
                        ev.status === 'completed' ? 'SUCCESS' : ev.status === 'failed' ? 'FAILED' : ev.status,
                branch: ev.branch || 'main',
                failure_type: ev.failure_type || null,
                severity: ev.severity || (ev.failure_type ? 'HIGH' : null),
                recovery: ev.recovery_action || (ev.recovery ? 'TRIGGERED' : null),
                recovery_triggered: !!ev.recovery_action || !!ev.recovery,
                time: new Date(ev.submitted_at || Date.now()).toLocaleTimeString()
              };
              
              const existingIdx = newEvents.findIndex(x => x.job_id === ev.job_id);
              if (existingIdx >= 0) {
                 if (JSON.stringify(newEvents[existingIdx]) !== JSON.stringify(mapped)) {
                    newEvents[existingIdx] = mapped;
                    changed = true;
                 }
              } else {
                 newEvents.unshift(mapped);
                 changed = true;
              }
            }
            if (changed) {
               const sorted = newEvents.sort((a,b) => new Date('1970/01/01 ' + b.time) - new Date('1970/01/01 ' + a.time)).slice(0, 50);
               localStorage.setItem('cicd_events', JSON.stringify(sorted));
               return sorted;
            }
            return prev;
          });
        }
      } catch (err) {
        // ignore api errors during poll
      }
    };
    fetchLiveEvents();
    const t = setInterval(fetchLiveEvents, 2500);
    return () => clearInterval(t);
  }, []);

  return (
    <Ctx.Provider value={{ toast, events, addEvent, clearEvents }}>
      {children}
      <div className="toast-wrap">
        {toasts.map(t => (
          <div key={t.id} className={`toast toast-${t.type === 'ok' ? 'ok' : t.type === 'error' ? 'err' : 'info'}`}>
            <span>{t.type === 'ok' ? '✓' : t.type === 'error' ? '✗' : 'ℹ'}</span>
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
