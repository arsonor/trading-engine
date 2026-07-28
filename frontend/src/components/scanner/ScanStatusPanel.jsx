/**
 * Scan status.
 *
 * The single requirement this component exists to satisfy: **"no candidates" and
 * "scanner broken" must not look the same.** They are different colours, different
 * icons and different copy, driven by `status.state` from the API rather than by
 * checking whether the alert list happens to be empty. An empty list is a normal,
 * frequent, healthy outcome; an outage is not, and a user who cannot tell them apart
 * will eventually trust neither.
 */

const STATE_PRESENTATION = {
  ok_with_candidates: {
    label: 'Scanner healthy',
    icon: '✓',
    box: 'border-emerald-300 bg-emerald-50',
    text: 'text-emerald-900',
    dot: 'bg-emerald-500',
  },
  ok_no_candidates: {
    label: 'Scanner healthy — quiet market',
    icon: '✓',
    box: 'border-slate-300 bg-slate-50',
    text: 'text-slate-800',
    dot: 'bg-slate-400',
  },
  skipped: {
    label: 'Outside scan window',
    icon: '◷',
    box: 'border-slate-300 bg-slate-50',
    text: 'text-slate-700',
    dot: 'bg-slate-400',
  },
  failed: {
    label: 'SCANNER FAILING',
    icon: '⚠',
    box: 'border-red-400 bg-red-50',
    text: 'text-red-900',
    dot: 'bg-red-500',
  },
  never_run: {
    label: 'Never run',
    icon: '—',
    box: 'border-amber-300 bg-amber-50',
    text: 'text-amber-900',
    dot: 'bg-amber-500',
  },
  unknown: {
    label: 'Status unavailable',
    icon: '?',
    box: 'border-amber-300 bg-amber-50',
    text: 'text-amber-900',
    dot: 'bg-amber-500',
  },
};

const STAGE_LABELS = [
  ['universe', 'Universe'],
  ['stage_1_liquidity', 'Stage 1 · liquidity'],
  ['stage_2_momentum', 'Stage 2 · gap + RVOL'],
  ['stage_3_room_to_run', 'Stage 3 · room to run'],
  ['risk_filters', 'Risk filters'],
];

function formatTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

export default function ScanStatusPanel({ status }) {
  if (!status) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-500">
        Loading scanner status…
      </div>
    );
  }

  const view = STATE_PRESENTATION[status.state] ?? STATE_PRESENTATION.unknown;
  const counts = status.last_run?.stage_counts?.counts;

  return (
    <section className={`rounded-lg border p-3 ${view.box}`} aria-live="polite">
      <div className="flex items-start gap-2">
        <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${view.dot}`} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h2 className={`text-sm font-semibold ${view.text}`}>
            <span aria-hidden="true" className="mr-1">
              {view.icon}
            </span>
            {view.label}
          </h2>
          <p className={`mt-0.5 text-xs leading-snug ${view.text}`}>{status.detail}</p>

          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-slate-600">
            <div>
              <dt className="inline text-slate-500">Last scan: </dt>
              <dd className="inline">{formatTime(status.last_run?.started_at)}</dd>
            </div>
            <div>
              <dt className="inline text-slate-500">Last success: </dt>
              <dd className="inline">{formatTime(status.last_successful_run?.started_at)}</dd>
            </div>
            {status.last_run?.profile && (
              <div>
                <dt className="inline text-slate-500">Profile: </dt>
                <dd className="inline font-medium">
                  {status.last_run.profile}
                  {status.last_run.is_demo && ' (demo)'}
                </dd>
              </div>
            )}
            <div>
              <dt className="inline text-slate-500">Candidates: </dt>
              <dd className="inline">{status.alert_count}</dd>
            </div>
          </dl>

          {counts && (
            <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-600">
              {STAGE_LABELS.map(([key, label]) =>
                counts[key] == null ? null : (
                  <li key={key}>
                    <span className="text-slate-500">{label}:</span>{' '}
                    <span className="font-medium text-slate-800">{counts[key]}</span>
                  </li>
                )
              )}
            </ul>
          )}

          {status.state === 'failed' && status.last_run?.error && (
            <pre className="mt-2 overflow-x-auto rounded bg-red-100 p-2 text-[11px] leading-snug text-red-900">
              {status.last_run.error}
            </pre>
          )}
        </div>
      </div>
    </section>
  );
}
