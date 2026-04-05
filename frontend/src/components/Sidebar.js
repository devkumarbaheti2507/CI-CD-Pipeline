import React from 'react';

const NAV = [
  { id: 'dashboard', label: 'Dashboard',          icon: '⬡' },
  { id: 'trigger',   label: 'Trigger Pipeline',   icon: '▶' },
  { id: 'logs',      label: 'Log Analyzer',        icon: '⌕' },
  { id: 'classify',  label: 'Failure Classifier',  icon: '⚡' },
  { id: 'recovery',  label: 'Recovery Manager',    icon: '↺' },
  { id: 'notify',    label: 'Notifications',       icon: '◎' },
  { id: 'settings',  label: 'Settings',            icon: '⚙' },
];

const S = {
  sidebar: {
    width: 216, minHeight: '100vh', background: '#0e1117',
    borderRight: '1px solid #252a38', display: 'flex',
    flexDirection: 'column', padding: '0 0 20px', position: 'fixed',
    top: 0, left: 0, bottom: 0, zIndex: 20,
  },
  logo: {
    padding: '22px 20px 18px', borderBottom: '1px solid #252a38', marginBottom: 8,
  },
  logoTitle: {
    fontFamily: "'IBM Plex Sans', sans-serif", fontSize: 15, fontWeight: 700,
    color: '#4f9eff', letterSpacing: '-.3px',
  },
  logoSub: { fontSize: 11, color: '#475569', marginTop: 3 },
  nav: { flex: 1 },
  item: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '9px 20px',
    cursor: 'pointer', fontSize: 13, fontWeight: 500, color: '#64748b',
    transition: 'all .12s', borderLeft: '2px solid transparent',
  },
  itemActive: {
    color: '#4f9eff', borderLeftColor: '#4f9eff',
    background: 'rgba(79,158,255,0.06)',
  },
  icon: { fontSize: 15, width: 18, textAlign: 'center', flexShrink: 0 },
  footer: {
    padding: '12px 20px', borderTop: '1px solid #252a38', marginTop: 8,
    fontSize: 11, color: '#334155', lineHeight: 2,
    fontFamily: "'IBM Plex Mono', monospace",
  },
};

export default function Sidebar({ page, setPage }) {
  return (
    <aside style={S.sidebar}>
      <div style={S.logo}>
        <div style={S.logoTitle}>CI/CD Pipeline</div>
        <div style={S.logoSub}>Automated Recovery System</div>
      </div>

      <nav style={S.nav}>
        {NAV.map(n => (
          <div
            key={n.id}
            style={{ ...S.item, ...(page === n.id ? S.itemActive : {}) }}
            onClick={() => setPage(n.id)}
          >
            <span style={S.icon}>{n.icon}</span>
            {n.label}
          </div>
        ))}
      </nav>

      <div style={S.footer}>
        :9000 controller{'\n'}
        :5001 analyzer{'\n'}
        :8000 classifier{'\n'}
        :6001 recovery{'\n'}
        :7000 notification
      </div>
    </aside>
  );
}
