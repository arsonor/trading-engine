/**
 * The framing the product spec requires: candidates, not predictions.
 *
 * `docs/CLAUDE.md` section 1 is explicit that this tool does not predict or promise a
 * 5% gain and is not financial advice. That has to appear where the numbers appear, not
 * only on an about page.
 */

export function CandidatesNotPredictions({ className = '' }) {
  return (
    <p className={`text-xs leading-snug text-slate-500 ${className}`}>
      These are <strong className="font-semibold text-slate-700">candidates, not predictions</strong>.
      The 5% figure is a feasibility screen — whether a move is structurally plausible — not a
      forecast that it will happen. Confidence scores are provisional and unvalidated. This is a
      decision-support tool, not financial advice.
    </p>
  );
}

export function DemoProfileBanner() {
  return (
    <div className="rounded-lg border-2 border-amber-400 bg-amber-50 p-3">
      <h2 className="text-sm font-bold text-amber-900">Demo profile active</h2>
      <p className="mt-1 text-xs leading-snug text-amber-900">
        Thresholds are deliberately loosened so the pipeline can be seen working on free-tier
        data, where every available symbol is a mega-cap that the real float filter rejects.
        These candidates are <strong>illustrative only</strong> and must not be treated as
        trading signals.
      </p>
    </div>
  );
}

export default CandidatesNotPredictions;
