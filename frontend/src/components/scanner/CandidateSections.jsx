/**
 * Confirmed candidates, and the ones that faded.
 *
 * A ticker qualifies at 05:10 and has four hours in which to stop qualifying. The alert
 * row is updated in place all morning, so by 09:26 the session's list holds both the
 * candidates that survived to the authoritative 09:25 pass and every one that spiked
 * earlier and died. Rendering them as one undifferentiated column asks the user to read
 * 37 cards to find the 11 that matter, at exactly the moment he is deciding what to
 * trade.
 *
 * So they are separated, using `is_final_pass` from the API — never by parsing the
 * `suggested_entry_window` string, which is prose written for a human.
 *
 * The faded ones are demoted, NOT dropped: a spike at 05:10 that faded is real
 * information, and Phase 6 outcome labelling will want it.
 *
 * Before 09:25 the split does not exist yet. Nothing is confirmed, so everything is
 * shown as provisional — calling those cards "faded" would be false, and calling them
 * "confirmed" would be worse.
 */

import { useState } from 'react';
import AlertCard from './AlertCard';
import { splitCandidates } from './candidates';

function CardList({ alerts, onMarkRead }) {
  return (
    <ul className="space-y-3">
      {alerts.map((alert) => (
        <li key={alert.id}>
          <AlertCard alert={alert} onMarkRead={onMarkRead} />
        </li>
      ))}
    </ul>
  );
}

function SectionHeading({ title, count, note }) {
  return (
    <div className="mb-2">
      <h2 className="text-sm font-semibold text-slate-900">
        {title} <span className="font-normal text-slate-500">({count})</span>
      </h2>
      <p className="mt-0.5 text-xs leading-snug text-slate-500">{note}</p>
    </div>
  );
}

export default function CandidateSections({ alerts, finalPassComplete, onMarkRead }) {
  const [showFaded, setShowFaded] = useState(false);
  const { confirmed, faded, provisional } = splitCandidates(alerts, finalPassComplete);

  if (!finalPassComplete) {
    return (
      <section>
        <SectionHeading
          title="Provisional candidates"
          count={provisional.length}
          note="Nothing is confirmed until the 09:25 ET pass — a candidate at 05:00 has four hours in which to stop being one."
        />
        <CardList alerts={provisional} onMarkRead={onMarkRead} />
      </section>
    );
  }

  return (
    <div className="space-y-5">
      <section>
        <SectionHeading
          title="Confirmed candidates"
          count={confirmed.length}
          note="Still qualifying at the authoritative 09:25 ET confirmation pass."
        />
        {confirmed.length > 0 ? (
          <CardList alerts={confirmed} onMarkRead={onMarkRead} />
        ) : (
          <p className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-center text-xs leading-snug text-slate-600">
            No candidate survived to the 09:25 pass. Everything below qualified earlier and
            faded before the open.
          </p>
        )}
      </section>

      {faded.length > 0 && (
        <section className="border-t border-slate-200 pt-3">
          <button
            type="button"
            onClick={() => setShowFaded((open) => !open)}
            aria-expanded={showFaded}
            className="text-sm font-medium text-slate-600 hover:text-slate-900"
          >
            {showFaded ? 'Hide' : 'Show'} earlier candidates ({faded.length})
          </button>
          <p className="mt-0.5 text-xs leading-snug text-slate-500">
            Qualified earlier in the session and then stopped — gap closed, RVOL fell away,
            or ran into resistance. Kept because that is real information, not because it is
            still actionable. Most recently seen first.
          </p>
          {showFaded && (
            <div className="mt-3 opacity-75">
              <CardList alerts={faded} onMarkRead={onMarkRead} />
            </div>
          )}
        </section>
      )}
    </div>
  );
}
