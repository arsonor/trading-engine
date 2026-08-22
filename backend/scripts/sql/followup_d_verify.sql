-- Follow-up D — Monday verification, 24 August 2026
-- Run after the 09:25 ET pass (15:25 CEST). Five checks, in the order that matters:
-- did it run, did it decide the same way, did it record the new evidence, did it cost
-- what was promised. All read-only.

-- ============================================================ V1 — did the morning run at all
-- Expect 19 completed, 0 failed, 0 stuck, 65 skips. Same as 18-21 August.
SELECT (started_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')::date AS et_date,
       count(*)                                     AS wakeups,
       count(*) FILTER (WHERE status = 'completed') AS completed,
       count(*) FILTER (WHERE status = 'failed')    AS failed,
       count(*) FILTER (WHERE status = 'running')   AS stuck,
       count(*) FILTER (WHERE status = 'skipped')   AS skipped
FROM scan_runs
WHERE started_at >= TIMESTAMP '2026-08-24'
GROUP BY 1 ORDER BY 1;

-- ============================================================ V2 — the funnel still reconciles
-- stage_1 = candidates + rejections, with NO remainder. This is the identity that held on
-- all eight sessions of the Phase 4 close; if full evaluation had started re-labelling
-- rejections, `remainder` would go non-zero. It is the sharpest single check here.
SELECT (started_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')::date AS et_date,
       ((stage_counts_json::jsonb)->'counts'->>'stage_1_liquidity')::int     AS stage1,
       jsonb_array_length((stage_counts_json::jsonb)->'candidates')          AS candidates,
       jsonb_array_length((stage_counts_json::jsonb)->'rejections')          AS rejections,
       ((stage_counts_json::jsonb)->'counts'->>'stage_1_liquidity')::int
         - jsonb_array_length((stage_counts_json::jsonb)->'candidates')
         - jsonb_array_length((stage_counts_json::jsonb)->'rejections')      AS remainder
FROM scan_runs
WHERE ((stage_counts_json::jsonb)->>'is_final_pass')::boolean IS TRUE
  AND status = 'completed'
  AND started_at >= TIMESTAMP '2026-08-24'
ORDER BY 1;

-- ============================================================ V3 — the new evidence is actually there
-- THE point of the change. Before Follow-up D, `with_rvol` on gap-rejected rows was 0.
-- Expect it to equal `rows` now. `no_snapshot_*` must stay fully NULL — that population
-- can never be evaluated, which is why sweep_limitations() still exists.
SELECT rejection_reason,
       count(*)                                    AS rows,
       count(gap_pct)                              AS with_gap,
       count(rvol_pct)                             AS with_rvol,
       count(upside_pct)                           AS with_upside
FROM scan_observations
WHERE session_date >= DATE '2026-08-24' AND is_final_pass
GROUP BY 1 ORDER BY 2 DESC;

-- ============================================================ V4 — it cost what was promised
-- "No extra API calls" was measured from `calls = stage_1 + 1`. That must still hold, and
-- duration should be essentially flat against the 65.9-67.7 s of 18-21 August: the added
-- work is ~680 in-memory RVOL computations against ~740 HTTP calls.
SELECT (started_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')::date AS et_date,
       ((stage_counts_json::jsonb)->'counts'->>'stage_1_liquidity')::int     AS stage1,
       api_calls_used                                                        AS calls,
       api_calls_used - ((stage_counts_json::jsonb)->'counts'->>'stage_1_liquidity')::int
                                                                             AS calls_over_stage1,
       round((((stage_counts_json::jsonb)->>'bytes_used')::bigint) / 1048576.0, 2) AS mb,
       round(((stage_counts_json::jsonb)->>'duration_s')::numeric, 1)        AS secs,
       ((stage_counts_json::jsonb)->>'observations_recorded')::int           AS observations
FROM scan_runs
WHERE ((stage_counts_json::jsonb)->>'is_final_pass')::boolean IS TRUE
  AND status = 'completed'
  AND started_at >= TIMESTAMP '2026-08-24'
ORDER BY 1;

-- ============================================================ V5 — the user's view is unchanged
-- Confirmed count should sit in the 3-14 band the Phase 4 close measured. A number outside
-- it is not proof of a bug — the market moves — but it is the cue to look at V2 and V3
-- before assuming it was the market.
SELECT session_date,
       count(*)                              AS alerts_session_total,
       count(*) FILTER (WHERE is_final_pass) AS confirmed_0925,
       round(min(confidence_score)::numeric, 3) AS score_min,
       round(max(confidence_score)::numeric, 3) AS score_max
FROM alerts
WHERE session_date >= DATE '2026-08-24'
GROUP BY 1 ORDER BY 1;
