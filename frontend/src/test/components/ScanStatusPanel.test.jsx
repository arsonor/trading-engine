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
});
