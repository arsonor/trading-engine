/**
 * Splitting a session's alerts into the confirmed set and the faded set.
 *
 * Its own module rather than a second export from `CandidateSections.jsx`: the rule this
 * encodes is worth testing directly, without rendering anything.
 */

/** Most recent sighting first — 09:20 and 04:30 are very different kinds of dead. */
function lastSeen(alert) {
  const raw = alert.scan_timestamp ?? alert.updated_at;
  const parsed = raw ? new Date(raw).getTime() : NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Confirmed = still qualifying at the authoritative 09:25 ET pass, taken from the API's
 * `is_final_pass` and never from parsing `suggested_entry_window`, which is prose.
 *
 * `finalPassComplete` also comes from the API, not from the clock and not from whether
 * any alert happens to carry the flag: a 09:25 pass that confirmed nothing is a real
 * outcome, and it must not be indistinguishable from 06:40, when nothing is confirmed
 * yet because nothing could be.
 */
export function splitCandidates(alerts = [], finalPassComplete = false) {
  if (!finalPassComplete) {
    return { confirmed: [], faded: [], provisional: alerts };
  }

  return {
    // Confidence order, as the API sent it.
    confirmed: alerts.filter((a) => a.is_final_pass),
    faded: alerts.filter((a) => !a.is_final_pass).sort((a, b) => lastSeen(b) - lastSeen(a)),
    provisional: [],
  };
}

export default splitCandidates;
