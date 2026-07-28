/**
 * Honesty badges.
 *
 * These are not decoration. A confidence score renders as an authoritative number
 * whether or not it has earned it, so the caveats have to sit next to it rather than in
 * a footnote nobody scrolls to. Every one of these corresponds to a flag the API sends
 * with the data.
 */

export function DemoBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900 ring-1 ring-amber-300"
      title="Loosened thresholds so the pipeline can be demonstrated on free-tier data. Not a real trading signal."
    >
      DEMO
    </span>
  );
}

export function ProvisionalBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-300"
      title="Confidence weights are reasoned assumptions, not backtested. Validation needs historical intraday data (app V3)."
    >
      provisional
    </span>
  );
}

export function ApproxRvolBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-300"
      title="RVOL compares partial pre-market volume against a full-day average — it is not time-of-day normalized."
    >
      RVOL approx
    </span>
  );
}

export function FinalPassBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 ring-1 ring-emerald-300"
      title="Produced by the authoritative 09:25 ET confirmation pass."
    >
      confirmed 09:25
    </span>
  );
}

/** Shown when a ticker trades above every known resistance level. */
export function NoResistanceBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-900 ring-1 ring-sky-300"
      title="Price is above every known resistance level, so headroom cannot be measured. Not the same as zero upside."
    >
      no overhead resistance
    </span>
  );
}

export default { DemoBadge, ProvisionalBadge, ApproxRvolBadge, FinalPassBadge, NoResistanceBadge };
