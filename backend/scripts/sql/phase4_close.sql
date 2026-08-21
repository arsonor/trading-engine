-- Phase 4 closing measurements — 21 August 2026
-- Run each block separately (the Supabase SQL editor returns only the last statement's
-- result: select one block and press Ctrl+Enter to run just that one).
-- Window starts 2026-08-12 — the first session where alerts persisted, i.e. when
-- `--no-alerts` was removed from the cron (commit 8279535).

-- ============================================================ Q1 — session ledger
SELECT
  session_date,
  count(*)                                     AS alerts_session_total,
  count(*) FILTER (WHERE is_final_pass)        AS confirmed_0925,
  count(*) FILTER (WHERE rvol_is_approximate)  AS rvol_approx,
  count(*) FILTER (WHERE upside_pct IS NULL)   AS upside_null,
  count(*) FILTER (WHERE catalyst IS NOT NULL) AS with_catalyst,
  min(rvol_mode)                               AS rvol_mode,
  min(profile)                                 AS profile,
  round(min(confidence_score)::numeric, 3)     AS score_min,
  round(avg(confidence_score)::numeric, 3)     AS score_avg,
  round(max(confidence_score)::numeric, 3)     AS score_max
FROM alerts
WHERE session_date >= DATE '2026-08-12'
GROUP BY session_date
ORDER BY session_date;

-- ============================================================ Q2 — the confirmed list the user actually sees, ranked
SELECT session_date, rnk, ticker, score, gap_pct, rvol_pct, upside_pct, resistance_source, approx
FROM (
  SELECT session_date, ticker,
         round(confidence_score::numeric, 3) AS score,
         round(gap_pct::numeric, 2)          AS gap_pct,
         round(rvol_pct::numeric, 1)         AS rvol_pct,
         round(upside_pct::numeric, 2)       AS upside_pct,
         resistance_source,
         rvol_is_approximate                 AS approx,
         row_number() OVER (PARTITION BY session_date
                            ORDER BY confidence_score DESC NULLS LAST) AS rnk
  FROM alerts
  WHERE is_final_pass AND session_date >= DATE '2026-08-12'
) t
WHERE rnk <= 10
ORDER BY session_date, rnk;

-- ============================================================ Q3 — does the ranking separate, or is it bunched?
WITH c AS (
  SELECT session_date, confidence_score AS s,
         row_number() OVER (PARTITION BY session_date
                            ORDER BY confidence_score DESC NULLS LAST) AS rnk
  FROM alerts
  WHERE is_final_pass AND session_date >= DATE '2026-08-12'
)
SELECT session_date,
       count(*)                                                    AS confirmed,
       round(max(s)::numeric, 3)                                   AS top,
       round(max(s) FILTER (WHERE rnk = 3)::numeric, 3)            AS rank3,
       round(max(s) FILTER (WHERE rnk = 5)::numeric, 3)            AS rank5,
       round(min(s)::numeric, 3)                                   AS bottom,
       round((max(s) - max(s) FILTER (WHERE rnk = 5))::numeric, 3) AS top_minus_rank5,
       round(stddev_pop(s)::numeric, 4)                            AS sd
FROM c
GROUP BY session_date
ORDER BY session_date;

-- ============================================================ Q4 — which factors actually move the ranking
SELECT f->>'name'                                           AS factor,
       round(avg((f->>'weight')::numeric), 3)               AS weight,
       round(avg((f->>'normalized')::numeric), 3)           AS avg_norm,
       round(stddev_pop((f->>'normalized')::numeric), 4)    AS sd_norm,
       round(min((f->>'normalized')::numeric), 3)           AS min_norm,
       round(max((f->>'normalized')::numeric), 3)           AS max_norm,
       count(*) FILTER (WHERE (f->>'is_fallback')::boolean) AS fallbacks,
       count(*)                                             AS n
FROM alerts a,
     jsonb_array_elements((a.score_breakdown_json::jsonb)->'factors') f
WHERE a.is_final_pass AND a.session_date >= DATE '2026-08-12'
GROUP BY 1
ORDER BY sd_norm DESC;

-- ============================================================ Q5 — run health per ET session (cadence before/after)
SELECT (started_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')::date AS et_date,
       count(*)                                     AS wakeups,
       count(*) FILTER (WHERE status = 'completed') AS completed,
       count(*) FILTER (WHERE status = 'failed')    AS failed,
       count(*) FILTER (WHERE status = 'running')   AS stuck_running,
       count(*) FILTER (WHERE status = 'skipped'
              AND (stage_counts_json::jsonb)->>'skip_reason' = 'off_cadence')    AS skip_off_cadence,
       count(*) FILTER (WHERE status = 'skipped'
              AND (stage_counts_json::jsonb)->>'skip_reason' = 'outside_window') AS skip_outside_window,
       count(*) FILTER (WHERE status = 'skipped'
              AND (stage_counts_json::jsonb)->>'skip_reason' IS NULL)            AS skip_no_reason,
       sum(api_calls_used)                          AS calls,
       round(sum(coalesce(((stage_counts_json::jsonb)->>'bytes_used')::bigint, 0)) / 1048576.0, 1) AS mb,
       round(max(((stage_counts_json::jsonb)->>'duration_s')::numeric), 1)       AS slowest_s
FROM scan_runs
WHERE started_at >= TIMESTAMP '2026-08-12'
GROUP BY 1
ORDER BY 1;

-- ============================================================ Q6 — the authoritative 09:25 pass, one row per session
-- Two fixes over the first version:
--   * `right(as_of_et, 8)` sliced the UTC offset and microseconds ("79-04:00"), not the
--     clock time. `substring(... from 12 for 5)` takes the HH:MM after the ISO "T".
--   * `is_final_pass` alone matched 18 skipped heartbeats a day as well as the real pass:
--     clock.py defines it as `at_minute(now) >= 09:25`, and the scan_runs row is opened
--     BEFORE the window gate, so every post-window wake-up carries it. Filter on
--     `status = 'completed'` too. See the note in docs/PLAN.md Phase 4.
SELECT (started_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')::date AS et_date,
       substring((stage_counts_json::jsonb)->>'as_of_et' from 12 for 5)      AS as_of_et,
       status,
       mode,
       ((stage_counts_json::jsonb)->'counts'->>'universe')::int            AS universe,
       ((stage_counts_json::jsonb)->'counts'->>'stage_1_liquidity')::int   AS stage1,
       ((stage_counts_json::jsonb)->'counts'->>'with_profile')::int        AS with_profile,
       ((stage_counts_json::jsonb)->'counts'->>'stage_2_momentum')::int    AS stage2,
       ((stage_counts_json::jsonb)->'counts'->>'stage_3_room_to_run')::int AS stage3,
       ((stage_counts_json::jsonb)->'counts'->>'risk_filters')::int        AS risk_ok,
       ((stage_counts_json::jsonb)->>'not_trading_count')::int             AS not_trading,
       (SELECT count(*) FROM jsonb_object_keys(
              coalesce((stage_counts_json::jsonb)->'snapshot_failures', '{}'::jsonb))) AS snap_fail,
       jsonb_array_length(coalesce((stage_counts_json::jsonb)->'integrity_warnings', '[]'::jsonb)) AS integrity,
       ((stage_counts_json::jsonb)->>'data_quality_suppressed')::int       AS suppressed,
       ((stage_counts_json::jsonb)->>'observations_recorded')::int         AS observations,
       api_calls_used                                                      AS calls,
       round((((stage_counts_json::jsonb)->>'bytes_used')::bigint) / 1048576.0, 2) AS mb,
       round(((stage_counts_json::jsonb)->>'duration_s')::numeric, 1)      AS secs
FROM scan_runs
WHERE ((stage_counts_json::jsonb)->>'is_final_pass')::boolean IS TRUE
  AND status = 'completed'
  AND started_at >= TIMESTAMP '2026-08-12'
ORDER BY 1;

-- ============================================================ Q7 — repeat names across sessions
SELECT ticker,
       count(*)                                 AS sessions_confirmed,
       round(avg(confidence_score)::numeric, 3) AS avg_score,
       round(avg(gap_pct)::numeric, 2)          AS avg_gap,
       min(session_date)                        AS first_seen,
       max(session_date)                        AS last_seen
FROM alerts
WHERE is_final_pass AND session_date >= DATE '2026-08-12'
GROUP BY ticker
HAVING count(*) > 1
ORDER BY 2 DESC, 3 DESC;

-- ============================================================ Q8 — where the funnel loses tickers at 09:25
SELECT r->>'stage' AS stage, r->>'reason' AS reason, count(*) AS n
FROM scan_runs,
     jsonb_array_elements(coalesce((stage_counts_json::jsonb)->'rejections', '[]'::jsonb)) r
WHERE ((stage_counts_json::jsonb)->>'is_final_pass')::boolean IS TRUE
  AND started_at >= TIMESTAMP '2026-08-12'
GROUP BY 1, 2
ORDER BY n DESC
LIMIT 25;

-- ============================================================ Q9 — bandwidth and call draw, actual
SELECT budget_date,
       calls_used,
       round(bytes_used / 1048576.0, 1) AS mb
FROM api_budget
WHERE budget_date >= DATE '2026-07-23'
ORDER BY budget_date;

-- ============================================================ Q10 — Phase 6 evidence actually accumulating
SELECT count(*)                    AS observation_rows,
       count(DISTINCT scan_run_id) AS runs,
       min(created_at)             AS first_row,
       max(created_at)             AS last_row
FROM scan_observations;
