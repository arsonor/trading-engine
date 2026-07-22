# Trading Engine — Implementation Plan (v2)

> Companion documents: `docs/CLAUDE.md` (specification) and `docs/PROMPT.md`
> (ready-to-use Claude Code prompts, one per phase).

---

## Objective

Rebuild the trading engine as an **alerts-only pre-market universe scanner** on FMP data,
deployed as Render (backend + cron) + Vercel (frontend) + Supabase (PostgreSQL), reachable
by URL on desktop and mobile.

---

## v1 Status (what already exists)

Completed and reusable:
- FastAPI + async SQLAlchemy backend, Alembic migrations, `uv` tooling
- React 19 / Vite / Zustand / Tailwind frontend with pages: Dashboard, Alerts, Rules, Settings
- Client WebSocket channel with live alert broadcast
- OpenAPI design-first contract (`openapi/spec.yaml`) + generated TS types
- Test suite (~263 tests) and GitHub Actions CI/CD
- Deployed on Render (free tier)
- MCP server with 17 custom tools + 5 resources

Completed but **being retired** in v2:
- Alpaca client + stream manager (`alpaca_client.py`, `stream_manager.py`)
- Watchlist-driven streaming model
- Per-tick YAML rule engine as the primary trigger
- Alpaca MCP integration (43 trading tools) — no trading in v2

---

## Migration Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Data provider | **FMP** | Only affordable provider bundling price + volume + **float** + screener + news |
| Trading | **None** | User trades elsewhere; drops broker dependency entirely |
| Local DB | **PostgreSQL** | Parity with production; removes SQLite-only bugs |
| Prod DB | **Supabase** | Free tier persists (does not delete after 30 days like Render free PG) |
| Backend host | **Render** (web + cron) | Already configured; cron only bills for run time |
| Frontend host | **Vercel** | Free, always-on, mirrors owner's other project stack |
| Scan window | **04:00 → 09:25 ET**, every 5 min | Captures full early session, not just 09:00–09:25 |
| RVOL | **Time-of-day normalized** | More accurate; requires a premarket volume profile |
| Scheduler | **Render Cron Job** | Cheaper than always-on compute for scheduled work |

---

## Phase Roadmap

### Phase 0 — Infrastructure Migration
**Goal:** Postgres everywhere; Render/Vercel/Supabase topology wired; cron placeholder.
**Depends on:** nothing. Provider-independent — safe to start immediately.

- [ ] Postgres for local dev via `docker-compose.dev.yml`; remove SQLite support
- [ ] Audit + fix SQLite-specific assumptions (types, defaults, batch migrations)
- [ ] Verify all Alembic migrations run clean against empty Postgres
- [ ] Consolidate settings in `config.py`; add `FMP_API_KEY` placeholder
- [ ] Supabase pooled-connection compatibility (pgBouncer / prepared statements)
- [ ] Rewrite `render.yaml`: always-on web service + **cron job stub**; remove Render PG
- [ ] Vercel config; API/WS URLs via env only (no hardcoded hosts)
- [ ] `/health` reports DB connectivity
- [ ] README "Getting started" rewritten and verified

**Done when:** clean checkout → docker up → migrate → backend + frontend run → existing
seed/simulate smoke test still produces a visible alert.

---

### Phase 1 — FMP Client & Reference-Data Pipeline
**Goal:** The nightly backbone. Everything downstream depends on this.
**Depends on:** Phase 0.

- [ ] FMP API client: auth, retries, backoff, rate-limit awareness, typed responses
- [ ] **Fixture recorder** — capture real FMP responses to disk for offline tests
- [ ] Universe sync: tradable US equities → `universe` table
- [ ] Reference data job → `reference_data`: float, 20d avg volume, prior close,
      prior high, 20d high, SMA-50, SMA-200
- [ ] **Premarket volume profile** → `premarket_volume_profile`: cumulative volume in
      5-min buckets from 04:00 ET, averaged over 20 sessions, per ticker
- [ ] Alembic migrations for all new tables + indexes for the Stage-1 query
- [ ] CLI entrypoint: `scripts/refresh_reference_data.py`
- [ ] Idempotent + resumable (survives partial failure without corrupting the table)

**Risk:** this phase exposes whether the chosen FMP tier really provides extended-hours
intraday history. **Validate before building the profile job.**

---

### Phase 2 — The Scanner Pipeline
**Goal:** The 3-stage filtration engine.
**Depends on:** Phase 1.

- [ ] Stage 1: SQL candidate query (float < 75M, avg vol > 500K) + price floor
- [ ] Stage 2: gap% (3–15) and time-of-day-normalized RVOL (>10%) over candidates
- [ ] Stage 3: nearest resistance + upside% (>= 5.5%) confirmation
- [ ] Risk filters: price floor, min dollar volume, market-wide tape check
- [ ] Injectable clock (no direct `datetime.now()` in logic) + explicit ET/DST handling
- [ ] `scan_runs` persistence: per-stage counts, timing, errors — full observability
- [ ] Stateless run design: recompute accumulated volume from 04:00 ET each pass
- [ ] Golden-case boundary tests + fixture-replay tests (no live API in CI)
- [ ] CLI: `scripts/run_scan.py` with `--dry-run`, `--fixture`, `--at <ET time>`

---

### Phase 3 — Scoring, Alerts & Dashboard
**Goal:** Turn survivors into alerts the end user can read on a phone.
**Depends on:** Phase 2.

- [ ] Confidence score: documented weighted formula, constants in config, flagged provisional
- [ ] Extend `alerts` model + schemas to the v2 output contract
- [ ] Persist alerts, deduplicate within a session, broadcast over existing WebSocket
- [ ] Redesign alert card: ticker, gap%, RVOL, catalyst, confidence, entry window
- [ ] Scan-run history view (what ran, how many survived each stage)
- [ ] Settings page: edit scanner thresholds without redeploy
- [ ] Mobile-first responsive pass — primary consumption device is a phone
- [ ] Explicit "candidates, not predictions / not financial advice" framing in UI
- [ ] Update `openapi/spec.yaml` + regenerate TS types

---

### Phase 4 — Enrichment
**Goal:** The confirmation signals from the spec's layer 2 and 3.
**Depends on:** Phase 3.

- [ ] Catalyst detection: FMP news + earnings calendar tagging
- [ ] Sector / index relative strength
- [ ] Bid-ask spread filter (slippage guard)
- [ ] Short interest (slow signal — FINRA lag ~2×/month, label accordingly)
- [ ] Halt-risk flag (best-effort heuristic; document limitations honestly)
- [ ] Gap-and-go historical pattern per ticker (has it made 5%+ first-hour moves before)

---

### Phase 5 — Backtesting & Calibration
**Goal:** Replace guessed weights with fitted ones. The spec explicitly demands this.
**Depends on:** Phase 4 + historical intraday data availability.

- [ ] Historical replay harness over past pre-market sessions (extended hours required)
- [ ] Outcome labelling: did the candidate reach +5% within the first hour?
- [ ] Per-signal hit-rate analysis (which filters actually predict)
- [ ] Fit confidence weights against outcomes; report precision/recall honestly
- [ ] Threshold sensitivity sweep to justify 3%/15%/10%/5.5% (or revise them)
- [ ] Publish results into the dashboard so the score's basis is visible

> Until Phase 5 completes, **the confidence score is an assumption, not a model.**

---

### Phase 6 — Hardening (deferred, revisit before wider use)
- [ ] Authentication on the dashboard (currently open by explicit decision)
- [ ] Push / email notification delivery at 09:25 ET
- [ ] Cost + rate-limit monitoring on FMP usage
- [ ] Uptime monitoring and scan-failure alerting (a silent failed scan is the worst bug)
- [ ] Decide fate of the MCP server (retain custom tools, drop Alpaca trading tools)

---

## Sequencing Rules

1. **Phase 0 first** — it is provider-independent and unblocks everything.
2. **Do not build Phase 2 before Phase 1's reference tables exist.** The scanner is a
   thin layer over pre-computed data; building it first inverts the dependency.
3. **Validate FMP capabilities before Phase 1's profile job.** If extended-hours
   intraday history is unavailable or too shallow, the RVOL definition must be
   renegotiated — better to learn this in Phase 1 than Phase 5.
4. **Never let CI depend on live market data or market hours.** Fixtures always.
5. One phase per Claude Code session; verify the "done when" before moving on.

---

## Known Risks

| Risk | Impact | Mitigation |
|---|---|---|
| FMP lacks 04:00 ET intraday coverage | Breaks full-early-session requirement | Validate first; fall back to 08:00 start or simpler RVOL |
| Historical intraday too shallow/costly | Blocks volume profile + backtesting | Check depth before Phase 1; may need a higher tier |
| Rate limits vs. universe size | Scan can't finish in window | Stage 1 shrinks universe first; batch + cache aggressively |
| Render cron UTC/DST drift | Scans fire at the wrong hour twice a year | Explicit ET conversion + DST tests |
| Silent scan failure | User sees no alerts, assumes no candidates | `scan_runs` table + failure alerting + UI "last successful scan" |
| Over-trusting the confidence score | User treats assumptions as validated | Label provisional; prioritise Phase 5 |
| Old `backup.sql` restore | Legacy alerts reference dead rule IDs | Do **not** bulk-restore into Supabase |

---

## Legacy Note

`backup.sql` (~34 MB) at repo root is a dump of the old Render PostgreSQL database. Its
alert rows reference DB-stored rule IDs that no longer exist (rules moved to YAML), and
its schema predates the v2 alert contract. Do not restore it wholesale. Extract the
watchlist only, if anything.
