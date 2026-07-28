/**
 * One candidate, as a card. The phone is the primary device, so this is a single
 * column that stays readable at 390px — a metric grid rather than a table, because a
 * table with seven numeric columns cannot be read on a phone without pinching.
 *
 * `upside_pct` and `nearest_resistance` may be null: a ticker trading above every known
 * resistance level has UNMEASURED headroom, not zero. That renders as its own state
 * rather than a dash or a 0, so the distinction survives all the way to the screen.
 */

import { useState } from 'react';
import ConfidenceBreakdown from './ConfidenceBreakdown';
import {
  ApproxRvolBadge,
  DemoBadge,
  FinalPassBadge,
  NoResistanceBadge,
  ProvisionalBadge,
} from './Badges';

const fmtPct = (value) => (value == null ? null : `${value.toFixed(2)}%`);
const fmtPrice = (value) => (value == null ? null : `$${value.toFixed(2)}`);

const RESISTANCE_LABELS = {
  high_yesterday: "yesterday's high",
  high_20d: '20-day high',
  sma_50: '50-day SMA',
  sma_200: '200-day SMA',
};

function Metric({ label, value, hint, emphasis = false }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd
        className={`truncate ${emphasis ? 'text-lg font-semibold' : 'text-sm font-medium'} text-slate-900`}
        title={hint}
      >
        {value ?? <span className="text-slate-400">—</span>}
      </dd>
    </div>
  );
}

function ConfidenceDial({ score }) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  // Deliberately muted colours: a green ring on an unvalidated score would imply an
  // endorsement the number has not earned.
  const tone =
    pct >= 60 ? 'text-slate-900 ring-slate-400' : pct >= 35 ? 'text-slate-700 ring-slate-300' : 'text-slate-500 ring-slate-200';
  return (
    <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full ring-2 ${tone}`}>
      <span className="text-sm font-bold">{pct}</span>
    </div>
  );
}

export default function AlertCard({ alert, onMarkRead }) {
  const [showBreakdown, setShowBreakdown] = useState(false);
  const hasUpside = alert.upside_pct != null;

  return (
    <article
      className={`rounded-lg border bg-white p-3 shadow-sm ${
        alert.is_demo ? 'border-amber-300' : 'border-slate-200'
      } ${alert.is_read ? 'opacity-70' : ''}`}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-xl font-bold tracking-tight text-slate-900">{alert.ticker}</h3>
            {alert.is_demo && <DemoBadge />}
            {alert.is_final_pass && <FinalPassBadge />}
          </div>
          <p className="mt-0.5 text-xs text-slate-500">
            {alert.suggested_entry_window || 'entry window not set'}
          </p>
        </div>
        <ConfidenceDial score={alert.confidence_score} />
      </header>

      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-3 sm:grid-cols-4">
        <Metric label="Gap" value={fmtPct(alert.gap_pct)} emphasis />
        <Metric
          label="RVOL"
          value={fmtPct(alert.rvol_pct)}
          hint={alert.rvol_is_approximate ? 'Approximate — not time-of-day normalized' : undefined}
          emphasis
        />
        <Metric label="Entry ref." value={fmtPrice(alert.entry_reference_price)} />
        {hasUpside ? (
          <Metric
            label="Upside"
            value={fmtPct(alert.upside_pct)}
            hint={`To ${RESISTANCE_LABELS[alert.resistance_source] ?? alert.resistance_source} at ${fmtPrice(alert.nearest_resistance)}`}
            emphasis
          />
        ) : (
          <Metric label="Upside" value={<span className="text-sm text-sky-800">unmeasured</span>} />
        )}
      </dl>

      {hasUpside ? (
        <p className="mt-2 text-xs text-slate-500">
          Nearest resistance: {fmtPrice(alert.nearest_resistance)} (
          {RESISTANCE_LABELS[alert.resistance_source] ?? alert.resistance_source})
        </p>
      ) : (
        <div className="mt-2">
          <NoResistanceBadge />
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {alert.rvol_is_approximate && <ApproxRvolBadge />}
        {alert.score_breakdown?.is_provisional && <ProvisionalBadge />}
        {alert.catalyst ? (
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
            {alert.catalyst}
          </span>
        ) : (
          <span className="text-xs text-slate-400">no catalyst data (Phase 4)</span>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-100 pt-2">
        <button
          type="button"
          onClick={() => setShowBreakdown((open) => !open)}
          className="text-sm font-medium text-primary-600 hover:text-primary-700"
          aria-expanded={showBreakdown}
        >
          {showBreakdown ? 'Hide' : 'Why this score?'}
        </button>
        {!alert.is_read && onMarkRead && (
          <button
            type="button"
            onClick={() => onMarkRead(alert.id)}
            className="text-sm text-slate-500 hover:text-slate-700"
          >
            Mark read
          </button>
        )}
      </div>

      {showBreakdown && <ConfidenceBreakdown breakdown={alert.score_breakdown} />}
    </article>
  );
}
