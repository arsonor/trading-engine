/**
 * Scan history — the audit trail.
 *
 * Every run appears with its status, so a string of `failed` rows is visible as such
 * rather than showing up as an unexplained absence of alerts.
 */

import { useEffect } from 'react';
import { useScannerStore } from '../store';
import ScanStatusPanel from '../components/scanner/ScanStatusPanel';

const STATUS_STYLES = {
  completed: 'bg-emerald-100 text-emerald-800 ring-emerald-300',
  failed: 'bg-red-100 text-red-800 ring-red-300',
  skipped: 'bg-slate-100 text-slate-600 ring-slate-300',
  running: 'bg-amber-100 text-amber-800 ring-amber-300',
};

function StatusPill({ status }) {
  const style = STATUS_STYLES[status] ?? 'bg-slate-100 text-slate-600 ring-slate-300';
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${style}`}>
      {status}
    </span>
  );
}

function ScanRunRow({ run }) {
  const counts = run.stage_counts?.counts;
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <StatusPill status={run.status} />
          {run.profile && (
            <span className="text-xs text-slate-600">
              {run.profile}
              {run.is_demo && <span className="ml-1 font-semibold text-amber-700">DEMO</span>}
            </span>
          )}
          {/* During the observation stage a completely healthy run produces zero alerts
              BY DESIGN. Without this badge that is indistinguishable from a quiet market,
              which is the same conflation the status pill exists to prevent. */}
          {run.mode === 'observation' && (
            <span
              className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-700 ring-1 ring-sky-300"
              title="Observation mode: the scan ran and was recorded, but no alerts were persisted or broadcast."
            >
              no alerts
            </span>
          )}
        </div>
        <span className="font-mono text-[11px] text-slate-500">
          {new Date(run.started_at).toLocaleString()}
        </span>
      </div>

      {counts && (
        <p className="mt-2 font-mono text-[11px] text-slate-600">
          {counts.universe ?? 0} → {counts.stage_1_liquidity ?? 0} → {counts.stage_2_momentum ?? 0}{' '}
          → {counts.stage_3_room_to_run ?? 0} → {counts.risk_filters ?? 0}
        </p>
      )}

      {run.error && (
        <pre className="mt-2 overflow-x-auto rounded bg-red-50 p-2 text-[11px] leading-snug text-red-900">
          {run.error}
        </pre>
      )}
    </li>
  );
}

export default function ScansPage() {
  const { scanRuns, status, fetchScanRuns, fetchStatus } = useScannerStore();

  useEffect(() => {
    fetchScanRuns();
    fetchStatus();
  }, [fetchScanRuns, fetchStatus]);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-bold text-slate-900">Scan history</h1>
        <p className="text-xs text-slate-500">
          Funnel counts read: universe → stage 1 → stage 2 → stage 3 → risk filters
        </p>
      </header>

      <ScanStatusPanel status={status} />

      {scanRuns.length === 0 ? (
        <p className="text-sm text-slate-500">No scans recorded yet.</p>
      ) : (
        <ul className="space-y-2">
          {scanRuns.map((run) => (
            <ScanRunRow key={run.id} run={run} />
          ))}
        </ul>
      )}
    </div>
  );
}
