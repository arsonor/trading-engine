/**
 * Tests for the confirmed/faded split.
 *
 * The requirement: at 09:26 the user must be able to see which candidates are still
 * candidates without reading every card. These tests fail if the two sets are ever
 * merged back into one flat list, if the faded ones are dropped rather than demoted, or
 * if a mid-session list gets described as "faded" before anything could have faded.
 */

import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import CandidateSections from '../../components/scanner/CandidateSections';
import { splitCandidates } from '../../components/scanner/candidates';

const alert = (id, ticker, isFinalPass, scanTimestamp) => ({
  id,
  ticker,
  gap_pct: 7.0,
  rvol_pct: 250.0,
  upside_pct: 12.0,
  nearest_resistance: 30.0,
  resistance_source: 'high_20d',
  entry_reference_price: 26.5,
  confidence_score: 0.6,
  is_final_pass: isFinalPass,
  is_demo: false,
  is_read: false,
  scan_timestamp: scanTimestamp,
});

const confirmedA = alert(1, 'CNFA', true, '2026-08-14T13:25:10Z');
const fadedEarly = alert(2, 'DEAD', false, '2026-08-14T08:30:00Z');
const fadedLate = alert(3, 'RECENT', false, '2026-08-14T13:20:00Z');

describe('splitCandidates', () => {
  it('separates confirmed from faded once the final pass has run', () => {
    const { confirmed, faded } = splitCandidates(
      [confirmedA, fadedEarly, fadedLate],
      true
    );

    expect(confirmed.map((a) => a.ticker)).toEqual(['CNFA']);
    expect(faded.map((a) => a.ticker)).toEqual(['RECENT', 'DEAD']); // most recent first
  });

  it('treats everything as provisional before the final pass', () => {
    const { confirmed, faded, provisional } = splitCandidates([fadedEarly, fadedLate], false);

    expect(confirmed).toEqual([]);
    expect(faded).toEqual([]);
    expect(provisional).toHaveLength(2);
  });

  it('does not crash on a missing scan timestamp', () => {
    const undated = { ...fadedEarly, id: 9, scan_timestamp: null, updated_at: null };
    const { faded } = splitCandidates([undated, fadedLate], true);

    expect(faded.map((a) => a.ticker)).toEqual(['RECENT', 'DEAD']);
  });
});

describe('CandidateSections', () => {
  it('shows confirmed candidates first and hides faded ones behind a toggle', () => {
    render(
      <CandidateSections alerts={[confirmedA, fadedEarly]} finalPassComplete onMarkRead={null} />
    );

    expect(screen.getByText(/Confirmed candidates/)).toBeInTheDocument();
    expect(screen.getByText('CNFA')).toBeInTheDocument();
    // Present, counted, but not competing for attention.
    expect(screen.getByText(/Show earlier candidates \(1\)/)).toBeInTheDocument();
    expect(screen.queryByText('DEAD')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText(/Show earlier candidates/));
    expect(screen.getByText('DEAD')).toBeInTheDocument();
  });

  it('does not describe a mid-session list as confirmed or faded', () => {
    render(<CandidateSections alerts={[fadedEarly, fadedLate]} finalPassComplete={false} />);

    expect(screen.getByText(/Provisional candidates/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is confirmed until the 09:25 ET pass/)).toBeInTheDocument();
    expect(screen.queryByText(/earlier candidates/)).not.toBeInTheDocument();
    // Nothing is hidden mid-session — every candidate is still live.
    expect(screen.getByText('DEAD')).toBeInTheDocument();
    expect(screen.getByText('RECENT')).toBeInTheDocument();
  });

  it('says so when the 09:25 pass confirmed nothing, rather than showing an empty column', () => {
    render(<CandidateSections alerts={[fadedEarly]} finalPassComplete />);

    expect(screen.getByText(/No candidate survived to the 09:25 pass/)).toBeInTheDocument();
    expect(screen.getByText(/Show earlier candidates \(1\)/)).toBeInTheDocument();
  });
});
