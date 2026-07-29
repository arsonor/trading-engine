import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import Layout from './components/common/Layout';
import DashboardPage from './pages/DashboardPage';
import ScansPage from './pages/ScansPage';
import SettingsPage from './pages/SettingsPage';
import { useAppStore } from './store';
import './App.css';

function App() {
  const { checkHealth } = useAppStore();

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, [checkHealth]);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="scans" element={<ScansPage />} />
          <Route path="settings" element={<SettingsPage />} />
          {/* Watchlist-era routes are retired: the per-tick rule engine is no longer the
              trigger path; the /rules API and its page went with it in Phase 3.5. */}
          <Route path="alerts" element={<Navigate to="/dashboard" replace />} />
          <Route path="rules" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
