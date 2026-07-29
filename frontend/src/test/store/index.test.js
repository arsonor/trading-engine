/**
 * Tests for Zustand stores
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';

// Mock the API services
vi.mock('../../services/api', () => ({
  watchlistApi: {
    list: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
  },
  healthApi: {
    check: vi.fn(),
  },
}));

describe('useWatchlistStore', () => {
  let useWatchlistStore;
  let watchlistApi;

  beforeEach(async () => {
    vi.resetModules();
    const storeModule = await import('../../store');
    useWatchlistStore = storeModule.useWatchlistStore;

    const apiModule = await import('../../services/api');
    watchlistApi = apiModule.watchlistApi;

    // Reset store state
    useWatchlistStore.setState({
      items: [],
      loading: false,
      error: null,
    });
  });

  it('has correct initial state', () => {
    const state = useWatchlistStore.getState();
    expect(state.items).toEqual([]);
    expect(state.loading).toBe(false);
    expect(state.error).toBe(null);
  });

  it('fetchWatchlist fetches and sets items', async () => {
    const mockItems = [{ id: 1, symbol: 'AAPL' }, { id: 2, symbol: 'GOOGL' }];
    watchlistApi.list.mockResolvedValue({ data: mockItems });

    await act(async () => {
      await useWatchlistStore.getState().fetchWatchlist();
    });

    const state = useWatchlistStore.getState();
    expect(state.items).toEqual(mockItems);
  });

  it('addSymbol prepends new item', async () => {
    useWatchlistStore.setState({
      items: [{ id: 1, symbol: 'AAPL' }],
    });

    const newItem = { id: 2, symbol: 'GOOGL', notes: 'Test' };
    watchlistApi.add.mockResolvedValue({ data: newItem });

    await act(async () => {
      await useWatchlistStore.getState().addSymbol('GOOGL', 'Test');
    });

    const state = useWatchlistStore.getState();
    expect(state.items.length).toBe(2);
    expect(state.items[0]).toEqual(newItem);
  });

  it('removeSymbol removes item from state', async () => {
    useWatchlistStore.setState({
      items: [{ id: 1, symbol: 'AAPL' }, { id: 2, symbol: 'GOOGL' }],
    });

    watchlistApi.remove.mockResolvedValue({});

    await act(async () => {
      await useWatchlistStore.getState().removeSymbol('AAPL');
    });

    const state = useWatchlistStore.getState();
    expect(state.items.length).toBe(1);
    expect(state.items[0].symbol).toBe('GOOGL');
  });
});

describe('useAppStore', () => {
  let useAppStore;
  let healthApi;

  beforeEach(async () => {
    vi.resetModules();
    const storeModule = await import('../../store');
    useAppStore = storeModule.useAppStore;

    const apiModule = await import('../../services/api');
    healthApi = apiModule.healthApi;

    // Reset store state
    useAppStore.setState({
      isConnected: false,
      healthStatus: null,
    });
  });

  it('has correct initial state', () => {
    const state = useAppStore.getState();
    expect(state.isConnected).toBe(false);
    expect(state.healthStatus).toBe(null);
  });

  it('setConnected updates connection status', () => {
    act(() => {
      useAppStore.getState().setConnected(true);
    });

    expect(useAppStore.getState().isConnected).toBe(true);

    act(() => {
      useAppStore.getState().setConnected(false);
    });

    expect(useAppStore.getState().isConnected).toBe(false);
  });

  it('checkHealth sets healthy status', async () => {
    healthApi.check.mockResolvedValue({ data: { status: 'healthy' } });

    await act(async () => {
      await useAppStore.getState().checkHealth();
    });

    const state = useAppStore.getState();
    expect(state.healthStatus).toEqual({ status: 'healthy' });
  });

  it('checkHealth sets unhealthy on error', async () => {
    healthApi.check.mockRejectedValue(new Error('Network error'));

    await act(async () => {
      await useAppStore.getState().checkHealth();
    });

    const state = useAppStore.getState();
    expect(state.healthStatus).toEqual({ status: 'unhealthy' });
  });
});
