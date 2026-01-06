/**
 * Tests for Layout component
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Layout from '../../components/common/Layout';

// Mock the stores
vi.mock('../../store', () => ({
  useAppStore: vi.fn(() => ({
    healthStatus: null,
    setConnected: vi.fn(),
  })),
  useAlertsStore: vi.fn(() => ({
    addAlert: vi.fn(),
    fetchStats: vi.fn(),
  })),
}));

// Mock the WebSocket hook
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

  it('renders the header with title', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(screen.getByText('Trading Alert Engine')).toBeInTheDocument();
  });

  it('renders all navigation items', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Alerts')).toBeInTheDocument();
    expect(screen.getByText('Rules')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('renders the footer', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(screen.getByText(/Trading Alert Engine v1.0.0/)).toBeInTheDocument();
    expect(screen.getByText(/Powered by Alpaca Markets/)).toBeInTheDocument();
  });

  it('shows disconnected status when not connected', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(screen.getByText('Disconnected')).toBeInTheDocument();
  });

  it('shows connected status when WebSocket is connected', async () => {
    const { default: useWebSocket } = await import('../../hooks/useWebSocket');
    useWebSocket.mockReturnValue({
      isConnected: true,
      lastMessage: null,
      subscribe: vi.fn(),
    });

    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(screen.getByText('Connected')).toBeInTheDocument();
  });

  it('shows API health status when available', async () => {
    const { useAppStore } = await import('../../store');
    useAppStore.mockReturnValue({
      healthStatus: { status: 'healthy' },
      setConnected: vi.fn(),
    });

    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    expect(screen.getByText('API: healthy')).toBeInTheDocument();
  });

  it('navigation links have correct paths', () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    );

    const dashboardLink = screen.getByText('Dashboard').closest('a');
    const alertsLink = screen.getByText('Alerts').closest('a');
    const rulesLink = screen.getByText('Rules').closest('a');
    const settingsLink = screen.getByText('Settings').closest('a');

    expect(dashboardLink).toHaveAttribute('href', '/dashboard');
    expect(alertsLink).toHaveAttribute('href', '/alerts');
    expect(rulesLink).toHaveAttribute('href', '/rules');
    expect(settingsLink).toHaveAttribute('href', '/settings');
  });
});
