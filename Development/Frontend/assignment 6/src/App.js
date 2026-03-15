import React, { useState } from 'react';
import { AppProvider } from './context/AppContext';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import TriggerPipeline from './pages/TriggerPipeline';
import LogAnalyzer from './pages/LogAnalyzer';
import FailureClassifier from './pages/FailureClassifier';
import RecoveryManager from './pages/RecoveryManager';
import Notifications from './pages/Notifications';
import Settings from './pages/Settings';

const PAGES = {
  dashboard: Dashboard,
  trigger:   TriggerPipeline,
  logs:      LogAnalyzer,
  classify:  FailureClassifier,
  recovery:  RecoveryManager,
  notify:    Notifications,
  settings:  Settings,
};

function Layout() {
  const [page, setPage] = useState('dashboard');
  const Page = PAGES[page] || Dashboard;

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar page={page} setPage={setPage} />
      <main style={{
        marginLeft: 216,
        flex: 1,
        padding: '32px 36px',
        maxWidth: 1200,
        minHeight: '100vh',
      }}>
        <Page />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Layout />
    </AppProvider>
  );
}
