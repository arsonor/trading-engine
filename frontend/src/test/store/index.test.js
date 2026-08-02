/**
 * Tests for Zustand stores
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from '@testing-library/react';

// Mock the API services
vi.mock('../../services/api', () => ({
  healthApi: {
    check: vi.fn(),
  },
}));

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
