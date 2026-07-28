/**
 * App shell.
 *
 * Mobile-first: the nav is a bottom tab bar on phones (thumb-reachable, the primary
 * device per the spec) and moves inline on wider screens. Nothing here may exceed the
 * viewport width at 390px.
 *
 * The Rules page is gone from the nav: the per-tick YAML rule engine is no longer the
 * trigger path. Its API and route survive until Alpaca is removed in its own commit.
 */

import { Outlet, NavLink } from 'react-router-dom';
import { useEffect } from 'react';
import { useAppStore, useScannerStore } from '../../store';
import useWebSocket from '../../hooks/useWebSocket';

const navItems = [
  { path: '/dashboard', label: 'Candidates', icon: '◎' },
  { path: '/scans', label: 'Scans', icon: '◷' },
  { path: '/settings', label: 'Settings', icon: '⚙' },
];

function Layout() {
  const { healthStatus, setConnected } = useAppStore();
  const { applyScanBroadcast, fetchStatus } = useScannerStore();
  const { isConnected, lastMessage, subscribe } = useWebSocket();

  useEffect(() => {
    setConnected(isConnected);
  }, [isConnected, setConnected]);

  useEffect(() => {
    if (isConnected) subscribe('alerts');
  }, [isConnected, subscribe]);

  // A scan push replaces the session's alert list and refreshes status — the scan that
  // produced the alerts also changed whether the scanner is considered healthy.
  useEffect(() => {
    if (lastMessage?.type === 'scan_alerts') {
      applyScanBroadcast(lastMessage.data);
      fetchStatus();
    }
  }, [lastMessage, applyScanBroadcast, fetchStatus]);

  return (
    <div className="min-h-screen bg-slate-50 pb-16 sm:pb-0">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-2 px-3 py-2">
          <h1 className="truncate text-sm font-bold text-slate-900">Pre-market Scanner</h1>
          <div className="flex shrink-0 items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${isConnected ? 'bg-emerald-500' : 'bg-slate-300'}`}
              title={isConnected ? 'Live updates connected' : 'Live updates disconnected'}
            />
            <span
              className={`h-2 w-2 rounded-full ${
                healthStatus?.status === 'healthy'
                  ? 'bg-emerald-500'
                  : healthStatus?.status === 'degraded'
                    ? 'bg-amber-500'
                    : 'bg-red-500'
              }`}
              title={`API: ${healthStatus?.status ?? 'unknown'}`}
            />
          </div>
        </div>

        {/* Wide screens: inline nav */}
        <nav className="mx-auto hidden max-w-3xl gap-1 px-3 sm:flex">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `border-b-2 px-3 py-2 text-sm font-medium ${
                  isActive
                    ? 'border-primary-500 text-primary-600'
                    : 'border-transparent text-slate-500 hover:text-slate-700'
                }`
              }
            >
              <span className="mr-1" aria-hidden="true">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-3xl px-3 py-4">
        <Outlet />
      </main>

      {/* Phones: bottom tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-slate-200 bg-white sm:hidden">
        <div className="flex">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${
                  isActive ? 'text-primary-600' : 'text-slate-500'
                }`
              }
            >
              <span className="text-base" aria-hidden="true">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-3 py-3">
          <p className="text-center text-[11px] leading-snug text-slate-400">
            Alerts only — this tool never places trades. Candidates are not predictions and
            this is not financial advice.
          </p>
        </div>
      </footer>
    </div>
  );
}

export default Layout;
