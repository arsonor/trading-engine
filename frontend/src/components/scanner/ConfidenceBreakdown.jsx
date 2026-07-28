/**
 * The per-factor justification behind a confidence score.
 *
 * The score is only defensible if the user can see how it was built, so every factor
 * shows its normalised value, its weight and what it contributed. Factors that fell back
 * because inputs were missing are marked, because "we scored this neutrally since we
 * could not measure it" is very different from "we measured it and it was mediocre".
 */

const pct = (value) => `${Math.round((value ?? 0) * 100)}%`;

const FACTOR_LABELS = {
  gap_position: 'Gap position',
  rvol: 'Relative volume',
  upside_headroom: 'Room to run',
  liquidity: 'Liquidity',
  data_quality: 'Data quality',
};

function FactorRow({ factor }) {
  const width = Math.max(0, Math.min(100, (factor.normalized ?? 0) * 100));
  return (
    <li className="py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-slate-800">
          {FACTOR_LABELS[factor.name] ?? factor.name}
          {factor.is_fallback && (
            <span
              className="ml-1 text-xs font-normal text-amber-700"
              title="This factor used a fallback because an input was missing or unreliable."
            >
              (fallback)
            </span>
          )}
        </span>
        <span className="shrink-0 font-mono text-xs text-slate-500">
          {pct(factor.normalized)} x {factor.weight} = {(factor.contribution ?? 0).toFixed(3)}
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full ${factor.is_fallback ? 'bg-amber-400' : 'bg-primary-500'}`}
          style={{ width: `${width}%` }}
        />
      </div>
      <p className="mt-1 text-xs leading-snug text-slate-500">{factor.detail}</p>
    </li>
  );
}

export default function ConfidenceBreakdown({ breakdown }) {
  if (!breakdown) {
    return <p className="text-sm text-slate-500">No score breakdown recorded.</p>;
  }

  return (
    <div className="mt-3 border-t border-slate-200 pt-3">
      <ul className="divide-y divide-slate-100">
        {(breakdown.factors ?? []).map((factor) => (
          <FactorRow key={factor.name} factor={factor} />
        ))}
      </ul>

      {(breakdown.notes ?? []).length > 0 && (
        <ul className="mt-3 space-y-1 rounded-md bg-slate-50 p-2">
          {breakdown.notes.map((note) => (
            <li key={note} className="text-xs leading-snug text-slate-600">
              {note}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
