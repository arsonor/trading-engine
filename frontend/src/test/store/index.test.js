/**
 * Tests for Zustand stores
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';

// Mock the API services
vi.mock('../../services/api', () => ({
  alertsApi: {
    list: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
    getStats: vi.fn(),
  },
  rulesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    toggle: vi.fn(),
  },
  watchlistApi: {
    list: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
  },
  healthApi: {
    check: vi.fn(),
  },
}));

describe('useAlertsStore', () => {
  let useAlertsStore;
  let alertsApi;

  beforeEach(async () => {
    vi.resetModules();
    const storeModule = await import('../../store');
    useAlertsStore = storeModule.useAlertsStore;

    const apiModule = await import('../../services/api');
    alertsApi = apiModule.alertsApi;

    // Reset store state
    useAlertsStore.setState({
      alerts: [],
      stats: null,
      loading: false,
      error: null,
      filters: {
        symbol: '',
        setup_type: '',
        is_read: null,
        page: 1,
        page_size: 50,
      },
      pagination: {
        total: 0,
        page: 1,
        page_size: 50,
        has_next: false,
        has_prev: false,
      },
    });
  });

  it('has correct initial state', () => {
    const state = useAlertsStore.getState();
    expect(state.alerts).toEqual([]);
    expect(state.stats).toBe(null);
    expect(state.loading).toBe(false);
    expect(state.error).toBe(null);
  });

  it('setFilters updates filters and resets page', () => {
    const { setFilters } = useAlertsStore.getState();

    act(() => {
      setFilters({ symbol: 'AAPL', page: 5 });
    });

    const state = useAlertsStore.getState();
    expect(state.filters.symbol).toBe('AAPL');
    expect(state.filters.page).toBe(1); // Reset to page 1
  });

  it('fetchAlerts sets loading and fetches data', async () => {
    const mockResponse = {
      data: {
        items: [{ id: 1, symbol: 'AAPL' }],
        total: 1,
        page: 1,
        page_size: 50,
        has_next: false,
        has_prev: false,
      },
    };
    alertsApi.list.mockResolvedValue(mockResponse);

    await act(async () => {
      await useAlertsStore.getState().fetchAlerts();
    });

    const state = useAlertsStore.getState();
    expect(state.loading).toBe(false);
    expect(state.alerts).toEqual(mockResponse.data.items);
    expect(state.pagination.total).toBe(1);
  });

  it('fetchAlerts handles errors', async () => {
    alertsApi.list.mockRejectedValue(new Error('Network error'));

    await act(async () => {
      await useAlertsStore.getState().fetchAlerts();
    });

    const state = useAlertsStore.getState();
    expect(state.loading).toBe(false);
    expect(state.error).toBe('Network error');
  });

  it('fetchStats updates stats', async () => {
    const mockStats = { total_alerts: 100, alerts_today: 10 };
    alertsApi.getStats.mockResolvedValue({ data: mockStats });

    await act(async () => {
      await useAlertsStore.getState().fetchStats();
    });

    const state = useAlertsStore.getState();
    expect(state.stats).toEqual(mockStats);
  });

  it('markAsRead updates alert in state', async () => {
    // Set initial state with an alert
    useAlertsStore.setState({
      alerts: [{ id: 1, symbol: 'AAPL', is_read: false }],
    });

    alertsApi.update.mockResolvedValue({ data: { id: 1, is_read: true } });

    await act(async () => {
      await useAlertsStore.getState().markAsRead(1);
    });

    const state = useAlertsStore.getState();
    expect(state.alerts[0].is_read).toBe(true);
  });

  it('addAlert prepends new alert', () => {
    useAlertsStore.setState({
      alerts: [{ id: 1, symbol: 'AAPL' }],
    });

    const newAlert = { id: 2, symbol: 'GOOGL' };

    act(() => {
      useAlertsStore.getState().addAlert(newAlert);
    });

    const state = useAlertsStore.getState();
    expect(state.alerts.length).toBe(2);
    expect(state.alerts[0]).toEqual(newAlert);
  });

  it('setPage updates page in filters', () => {
    act(() => {
      useAlertsStore.getState().setPage(3);
    });

    const state = useAlertsStore.getState();
    expect(state.filters.page).toBe(3);
  });
});

describe('useRulesStore', () => {
  let useRulesStore;
  let rulesApi;

  beforeEach(async () => {
    vi.resetModules();
    const storeModule = await import('../../store');
    useRulesStore = storeModule.useRulesStore;

    const apiModule = await import('../../services/api');
    rulesApi = apiModule.rulesApi;

    // Reset store state
    useRulesStore.setState({
      rules: [],
      loading: false,
      error: null,
    });
  });

  it('has correct initial state', () => {
    const state = useRulesStore.getState();
    expect(state.rules).toEqual([]);
    expect(state.loading).toBe(false);
    expect(state.error).toBe(null);
  });

  it('fetchRules fetches and sets rules', async () => {
    const mockRules = [{ id: 1, name: 'Rule 1' }, { id: 2, name: 'Rule 2' }];
    rulesApi.list.mockResolvedValue({ data: mockRules });

    await act(async () => {
      await useRulesStore.getState().fetchRules();
    });

    const state = useRulesStore.getState();
    expect(state.rules).toEqual(mockRules);
    expect(state.loading).toBe(false);
  });

  it('fetchRules handles errors', async () => {
    rulesApi.list.mockRejectedValue(new Error('Failed to fetch'));

    await act(async () => {
      await useRulesStore.getState().fetchRules();
    });

    const state = useRulesStore.getState();
    expect(state.error).toBe('Failed to fetch');
    expect(state.loading).toBe(false);
  });

  it('toggleRule updates rule in state', async () => {
    useRulesStore.setState({
      rules: [{ id: 1, name: 'Rule 1', is_active: true }],
    });

    rulesApi.toggle.mockResolvedValue({
      data: { id: 1, name: 'Rule 1', is_active: false },
    });

    await act(async () => {
      await useRulesStore.getState().toggleRule(1);
    });

    const state = useRulesStore.getState();
    expect(state.rules[0].is_active).toBe(false);
  });

  it('createRule adds new rule to state', async () => {
    const newRule = { name: 'New Rule', rule_type: 'breakout' };
    const createdRule = { id: 1, ...newRule };
    rulesApi.create.mockResolvedValue({ data: createdRule });

    await act(async () => {
      await useRulesStore.getState().createRule(newRule);
    });

    const state = useRulesStore.getState();
    expect(state.rules).toContainEqual(createdRule);
  });

  it('createRule throws on error', async () => {
    rulesApi.create.mockRejectedValue(new Error('Create failed'));

    await expect(
      useRulesStore.getState().createRule({ name: 'Test' })
    ).rejects.toThrow();
  });

  it('deleteRule removes rule from state', async () => {
    useRulesStore.setState({
      rules: [{ id: 1, name: 'Rule 1' }, { id: 2, name: 'Rule 2' }],
    });

    rulesApi.delete.mockResolvedValue({});

    await act(async () => {
      await useRulesStore.getState().deleteRule(1);
    });

    const state = useRulesStore.getState();
    expect(state.rules.length).toBe(1);
    expect(state.rules[0].id).toBe(2);
  });
});

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
