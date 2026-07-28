/**
 * The session view — the screen the user actually opens in the morning.
 *
 * Mobile-first: a single column of cards, no tables, nothing wider than the viewport.
 * Status sits above the alerts because "is the scanner even working?" has to be
 * answerable before any number on the page means anything.
 */

import { useEffect } from 'react';
import { useScannerStore } from '../store';
import AlertCard from '../components/scanner/AlertCard';
import ScanStatusPanel from '../components/scanner/ScanStatusPanel';
import { CandidatesNotPredictions, DemoProfileBanner } from '../components/scanner/Disclaimer';

function EmptyState({ status }) {
  // Only ever shown when the scanner is healthy — a failure is rendered by the status
  // panel above, never as an empty list.
  const isFailure = status && !status.is_healthy;
  if (isFailure) return null;

  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center">
      <p className="text-sm font-medium text-slate-700">No candidates this session</p>
      <p className="mt-1 text-xs leading-snug text-slate-500">
        The scanner ran successfully and nothing met the thresholds. That is a normal outcome —
        most sessions produce no candidates at all.
      </p>
    </div>
  );
}

export default function DashboardPage() {
  const {
    alerts,
    sessionDate,
    hasDemoAlerts,
    status,
    loading,
    error,
    fetchAlerts,
    fetchStatus,
    markRead,
  } = useScannerStore();

  useEffect(() => {
    fetchAlerts();
    fetchStatus();
    const interval = setInterval(fetchStatus, 60000);
    return () => clearInterval(interval);
  }, [fetchAlerts, fetchStatus]);

  const unreadCount = alerts.filter((a) => !a.is_read).length;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-bold text-slate-900">Pre-market candidates</h1>
        <p className="text-xs text-slate-500">
          {sessionDate ? `Session ${sessionDate}` : 'No session data yet'}
          {alerts.length > 0 && ` · ${alerts.length} candidate(s)`}
          {unreadCount > 0 && ` · ${unreadCount} unread`}
        </p>
      </header>

      <ScanStatusPanel status={status} />

      {hasDemoAlerts && <DemoProfileBanner />}

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          Could not load alerts: {error}
        </div>
      )}

      {loading && alerts.length === 0 ? (
        <p className="text-sm text-slate-500">Loading candidates…</p>
      ) : alerts.length === 0 ? (
        <EmptyState status={status} />
      ) : (
        <ul className="space-y-3">
          {alerts.map((alert) => (
            <li key={alert.id}>
              <AlertCard alert={alert} onMarkRead={markRead} />
            </li>
          ))}
        </ul>
      )}

      <CandidatesNotPredictions className="pt-2" />
    </div>
  );
}
