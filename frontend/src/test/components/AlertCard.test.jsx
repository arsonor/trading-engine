/**
 * Tests for the alert card.
 *
 * The null-upside case gets the most coverage here: a ticker trading above every known
 * resistance level has UNMEASURED headroom, and the card must say so rather than
 * rendering a 0, a dash, or crashing on `toFixed` of null.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import AlertCard from '../../components/scanner/AlertCard';

const baseAlert = {
  id: 1,
  ticker: 'ADBE',
  gap_pct: 7.0,
  rvol_pct: 25.0,
  rvol_is_approximate: true,
  confidence_score: 0.617,
  entry_reference_price: 240.87,
  nearest_resistance: 278.81,
  resistance_source: 'sma_200',
  upside_pct: 15.75,
  suggested_entry_window: '09:30-10:00 ET',
  profile: 'demo',
  is_demo: true,
  is_final_pass: true,
  is_read: false,
  catalyst: null,
  score_breakdown: {
    score: 0.617,
    is_provisional: true,
    uses_fallback: true,
    factors: [
      {
        name: 'upside_headroom',
        raw_value: 15.75,
        normalized: 0.93,
        weight: 0.25,
        contribution: 0.233,
        detail: '15.75% to sma_200',
        is_fallback: false,
      },
    ],
    notes: ['PROVISIONAL — weights are reasoned assumptions, not backtested.'],
  },
};

describe('AlertCard', () => {
  it('renders the core metrics', () => {
    render(<AlertCard alert={baseAlert} />);

    expect(screen.getByText('ADBE')).toBeInTheDocument();
    expect(screen.getByText('7.00%')).toBeInTheDocument();
    expect(screen.getByText('25.00%')).toBeInTheDocument();
    expect(screen.getByText('15.75%')).toBeInTheDocument();
    expect(screen.getByText('62')).toBeInTheDocument(); // confidence dial, 0-100
  });

  it('badges demo alerts so they cannot be mistaken for real signals', () => {
    render(<AlertCard alert={baseAlert} />);
    expect(screen.getByText('DEMO')).toBeInTheDocument();
  });

  it('flags approximate RVOL', () => {
    render(<AlertCard alert={baseAlert} />);
    expect(screen.getByText('RVOL approx')).toBeInTheDocument();
  });

  it('marks the score provisional', () => {
    render(<AlertCard alert={baseAlert} />);
    expect(screen.getByText('provisional')).toBeInTheDocument();
  });

  it('renders a null upside as unmeasured, not as zero', () => {
    const noResistance = {
      ...baseAlert,
      upside_pct: null,
      nearest_resistance: null,
      resistance_source: null,
    };
    render(<AlertCard alert={noResistance} />);

    expect(screen.getByText('unmeasured')).toBeInTheDocument();
    expect(screen.getByText('no overhead resistance')).toBeInTheDocument();
    expect(screen.queryByText('0.00%')).not.toBeInTheDocument();
  });

  it('does not crash when every optional metric is null', () => {
    const sparse = {
      id: 2,
      ticker: 'XYZ',
      gap_pct: null,
      rvol_pct: null,
      upside_pct: null,
      nearest_resistance: null,
      entry_reference_price: null,
      confidence_score: null,
      score_breakdown: null,
      is_demo: false,
      is_read: false,
    };
    render(<AlertCard alert={sparse} />);
    expect(screen.getByText('XYZ')).toBeInTheDocument();
  });

  it('shows the score breakdown on demand', () => {
    render(<AlertCard alert={baseAlert} />);

    expect(screen.queryByText(/15.75% to sma_200/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Why this score?'));
    expect(screen.getByText(/15.75% to sma_200/)).toBeInTheDocument();
    expect(screen.getByText(/PROVISIONAL/)).toBeInTheDocument();
  });

  it('says when catalyst data is unavailable rather than showing nothing', () => {
    render(<AlertCard alert={baseAlert} />);
    expect(screen.getByText(/no catalyst data/i)).toBeInTheDocument();
  });

  it('calls onMarkRead', () => {
    const onMarkRead = vi.fn();
    render(<AlertCard alert={baseAlert} onMarkRead={onMarkRead} />);

    fireEvent.click(screen.getByText('Mark read'));
    expect(onMarkRead).toHaveBeenCalledWith(1);
  });
});
