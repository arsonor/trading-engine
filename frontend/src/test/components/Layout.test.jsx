/**
 * Tests for the app shell.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Layout from '../../components/common/Layout';

vi.mock('../../store', () => ({
  useAppStore: vi.fn(() => ({
    healthStatus: null,
    setConnected: vi.fn(),
  })),
  useScannerStore: vi.fn(() => ({
    applyScanBroadcast: vi.fn(),
    fetchStatus: vi.fn(),
  })),
}));

vi.mock('../../hooks/useWebSocket', () => ({
  default: vi.fn(() => ({
    isConnected: false,
    lastMessage: null,
    subscribe: vi.fn(),
  })),
}));

describe('Layout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the header title', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );
    expect(screen.getByText('Pre-market Scanner')).toBeInTheDocument();
  });

  it('renders the v2 navigation and not the retired watchlist-era pages', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    // Each item appears twice: inline nav (wide) and bottom tab bar (phone).
    expect(screen.getAllByText('Candidates').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Scans').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Settings').length).toBeGreaterThan(0);
    expect(screen.queryByText('Rules')).not.toBeInTheDocument();
  });

  it('navigation links point at the v2 routes', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(screen.getAllByText('Candidates')[0].closest('a')).toHaveAttribute(
      'href',
      '/dashboard'
    );
    expect(screen.getAllByText('Scans')[0].closest('a')).toHaveAttribute('href', '/scans');
    expect(screen.getAllByText('Settings')[0].closest('a')).toHaveAttribute('href', '/settings');
  });

  it('states in the footer that the tool never trades and is not advice', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );
    expect(screen.getByText(/never places trades/i)).toBeInTheDocument();
    expect(screen.getByText(/not financial advice/i)).toBeInTheDocument();
  });

  it('subscribes to the alerts channel once connected', async () => {
    const subscribe = vi.fn();
    const { default: useWebSocket } = await import('../../hooks/useWebSocket');
    useWebSocket.mockReturnValue({ isConnected: true, lastMessage: null, subscribe });

    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(subscribe).toHaveBeenCalledWith('alerts');
  });

  it('applies a scan_alerts broadcast to the store', async () => {
    const applyScanBroadcast = vi.fn();
    const fetchStatus = vi.fn();
    const { useScannerStore } = await import('../../store');
    useScannerStore.mockReturnValue({ applyScanBroadcast, fetchStatus });

    const { default: useWebSocket } = await import('../../hooks/useWebSocket');
    useWebSocket.mockReturnValue({
      isConnected: true,
      lastMessage: { type: 'scan_alerts', data: { alerts: [], session_date: '2026-07-28' } },
      subscribe: vi.fn(),
    });

    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(applyScanBroadcast).toHaveBeenCalled();
    expect(fetchStatus).toHaveBeenCalled();
  });
});
