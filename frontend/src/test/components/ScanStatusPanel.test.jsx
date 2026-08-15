/**
 * Tests for the scan-status panel.
 *
 * The requirement under test is the one Phase 2 and 3 both exist to protect: a scan that
 * found nothing and a scan that broke must NOT look the same. These tests fail if
 * someone ever collapses the two states into one rendering.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ScanStatusPanel from '../../components/scanner/ScanStatusPanel';

const quietMarket = {
  state: 'ok_no_candidates',
  is_healthy: true,
  detail: 'Last scan completed successfully and found no candidates.',
  alert_count: 0,
  last_run: {
    id: 1,
    status: 'completed',
    profile: 'production',
    started_at: '2026-07-28T09:25:00Z',
    stage_counts: { counts: { universe: 10, stage_1_liquidity: 0 } },
  },
};

const brokenScanner = {
  state: 'failed',
  is_healthy: false,
  detail: 'The last scan FAILED: FeatureRequiresIntraday. This is an outage.',
  alert_count: 0,
  last_run: {
    id: 2,
    status: 'failed',
    profile: 'production',
    started_at: '2026-07-28T09:25:00Z',
    error: 'FeatureRequiresIntraday: needs extended=true bars',
  },
};

describe('ScanStatusPanel', () => {
  it('shows a quiet market as healthy', () => {
    render(<ScanStatusPanel status={quietMarket} />);

    expect(screen.getByText(/Scanner healthy/)).toBeInTheDocument();
    expect(screen.getByText(/found no candidates/)).toBeInTheDocument();
  });

  it('shows a failure as an outage, with the error', () => {
    render(<ScanStatusPanel status={brokenScanner} />);

    expect(screen.getByText(/SCANNER FAILING/)).toBeInTheDocument();
    expect(screen.getByText(/This is an outage/)).toBeInTheDocument();
    expect(screen.getByText(/FeatureRequiresIntraday: needs extended=true bars/)).toBeInTheDocument();
  });

  it('renders quiet and broken with visibly different styling', () => {
    const { container: quiet } = render(<ScanStatusPanel status={quietMarket} />);
    const quietClasses = quiet.querySelector('section').className;

    const { container: broken } = render(<ScanStatusPanel status={brokenScanner} />);
    const brokenClasses = broken.querySelector('section').className;

    expect(quietClasses).not.toEqual(brokenClasses);
    expect(brokenClasses).toMatch(/red/);
    expect(quietClasses).not.toMatch(/red/);
  });

  it('shows a never-run scanner as not healthy', () => {
    render(
      <ScanStatusPanel
        status={{ state: 'never_run', is_healthy: false, detail: 'never run', alert_count: 0 }}
      />
    );
    expect(screen.getByText(/Never run/)).toBeInTheDocument();
  });

  it('renders stage funnel counts when present', () => {
    render(<ScanStatusPanel status={quietMarket} />);
    expect(screen.getByText(/Universe:/)).toBeInTheDocument();
  });

  it('handles a missing status without crashing', () => {
    render(<ScanStatusPanel status={null} />);
    expect(screen.getByText(/Loading scanner status/)).toBeInTheDocument();
  });

  it('labels the confirmed count and the session total as different numbers', () => {
    render(
      <ScanStatusPanel
        status={{
          state: 'ok_with_candidates',
          is_healthy: true,
          detail: '11 candidate(s) confirmed at the 09:25 ET pass · 37 seen across the session.',
          alert_count: 37,
          confirmed_count: 11,
          final_pass_complete: true,
          last_run: { id: 3, status: 'completed', started_at: '2026-08-14T13:25:17Z' },
        }}
      />
    );

    expect(screen.getByText(/Confirmed at 09:25:/)).toBeInTheDocument();
    expect(screen.getByText('11')).toBeInTheDocument();
    expect(screen.getByText(/Seen this session:/)).toBeInTheDocument();
    expect(screen.getByText('37')).toBeInTheDocument();
  });

  it('shows the confirmed count as pending before the 09:25 pass, not as zero', () => {
    render(
      <ScanStatusPanel
        status={{
          state: 'ok_with_candidates',
          is_healthy: true,
          detail: '6 provisional candidate(s) so far this session.',
          alert_count: 6,
          confirmed_count: 0,
          final_pass_complete: false,
          last_run: { id: 4, status: 'completed', started_at: '2026-08-14T10:40:00Z' },
        }}
      />
    );

    expect(screen.getByText('pending')).toBeInTheDocument();
    // A "0" here would read as "nothing survived" rather than "not yet decided".
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });
});
