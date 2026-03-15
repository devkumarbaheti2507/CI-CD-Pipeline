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
