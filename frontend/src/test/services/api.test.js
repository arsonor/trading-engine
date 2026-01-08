/**
 * Tests for API service
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import axios from 'axios';

// Mock axios
vi.mock('axios', () => {
  const mockAxiosInstance = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  };

  // Direct axios methods (for calls like axios.get() instead of instance.get())
  const mockAxiosDirect = {
    get: vi.fn(),
    post: vi.fn(),
  };

  return {
    default: {
      create: vi.fn(() => mockAxiosInstance),
      get: mockAxiosDirect.get,
      post: mockAxiosDirect.post,
    },
  };
});

describe('API Service', () => {
  let api;
  let alertsApi;
  let rulesApi;
  let watchlistApi;
  let marketDataApi;
  let healthApi;
  let mockAxiosInstance;

  beforeEach(async () => {
    vi.resetModules();

    // Get mock axios instance
    mockAxiosInstance = axios.create();

    // Import the module fresh
    const apiModule = await import('../../services/api');
    api = apiModule.default;
    alertsApi = apiModule.alertsApi;
    rulesApi = apiModule.rulesApi;
    watchlistApi = apiModule.watchlistApi;
    marketDataApi = apiModule.marketDataApi;
    healthApi = apiModule.healthApi;

    // Reset mocks
    mockAxiosInstance.get.mockReset();
    mockAxiosInstance.post.mockReset();
    mockAxiosInstance.put.mockReset();
    mockAxiosInstance.patch.mockReset();
    mockAxiosInstance.delete.mockReset();
    axios.get.mockReset();
  });

  describe('alertsApi', () => {
    it('list calls GET /alerts with params', async () => {
      const params = { symbol: 'AAPL', page: 1 };
      mockAxiosInstance.get.mockResolvedValue({ data: { items: [] } });

      await alertsApi.list(params);

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/alerts', { params });
    });

    it('list with no params works', async () => {
      mockAxiosInstance.get.mockResolvedValue({ data: { items: [] } });

      await alertsApi.list();

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/alerts', { params: {} });
    });

    it('get calls GET /alerts/:id', async () => {
      mockAxiosInstance.get.mockResolvedValue({ data: { id: 1 } });

      await alertsApi.get(1);

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/alerts/1');
    });

    it('update calls PATCH /alerts/:id', async () => {
      const updateData = { is_read: true };
      mockAxiosInstance.patch.mockResolvedValue({ data: { id: 1, is_read: true } });

      await alertsApi.update(1, updateData);

      expect(mockAxiosInstance.patch).toHaveBeenCalledWith('/alerts/1', updateData);
    });

    it('getStats calls GET /alerts/stats', async () => {
      mockAxiosInstance.get.mockResolvedValue({ data: { total_alerts: 10 } });

      await alertsApi.getStats();

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/alerts/stats');
    });
  });

  describe('rulesApi', () => {
    it('list calls GET /rules', async () => {
      mockAxiosInstance.get.mockResolvedValue({ data: [] });

      await rulesApi.list();

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/rules');
    });

    it('get calls GET /rules/:id', async () => {
      mockAxiosInstance.get.mockResolvedValue({ data: { id: 1 } });

      await rulesApi.get(1);

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/rules/1');
    });

    it('create calls POST /rules', async () => {
      const ruleData = { name: 'Test Rule', rule_type: 'breakout' };
      mockAxiosInstance.post.mockResolvedValue({ data: { id: 1, ...ruleData } });

      await rulesApi.create(ruleData);

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/rules', ruleData);
    });

    it('update calls PUT /rules/:id', async () => {
      const updateData = { name: 'Updated Rule' };
      mockAxiosInstance.put.mockResolvedValue({ data: { id: 1, name: 'Updated Rule' } });

      await rulesApi.update(1, updateData);

      expect(mockAxiosInstance.put).toHaveBeenCalledWith('/rules/1', updateData);
    });

    it('delete calls DELETE /rules/:id', async () => {
      mockAxiosInstance.delete.mockResolvedValue({});

      await rulesApi.delete(1);

      expect(mockAxiosInstance.delete).toHaveBeenCalledWith('/rules/1');
    });

    it('toggle calls POST /rules/:id/toggle', async () => {
      mockAxiosInstance.post.mockResolvedValue({ data: { id: 1, is_active: false } });

      await rulesApi.toggle(1);

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/rules/1/toggle');
    });
  });

  describe('watchlistApi', () => {
    it('list calls GET /watchlist', async () => {
      mockAxiosInstance.get.mockResolvedValue({ data: [] });

      await watchlistApi.list();

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/watchlist');
    });

    it('add calls POST /watchlist', async () => {
      const itemData = { symbol: 'AAPL', notes: 'Test' };
      mockAxiosInstance.post.mockResolvedValue({ data: { id: 1, ...itemData } });

      await watchlistApi.add(itemData);

      expect(mockAxiosInstance.post).toHaveBeenCalledWith('/watchlist', itemData);
    });

    it('remove calls DELETE /watchlist/:symbol', async () => {
      mockAxiosInstance.delete.mockResolvedValue({});

      await watchlistApi.remove('AAPL');

      expect(mockAxiosInstance.delete).toHaveBeenCalledWith('/watchlist/AAPL');
    });
  });

  describe('marketDataApi', () => {
    it('get calls GET /market-data/:symbol', async () => {
      mockAxiosInstance.get.mockResolvedValue({ data: { symbol: 'AAPL' } });

      await marketDataApi.get('AAPL');

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/market-data/AAPL');
    });

    it('getHistory calls GET /market-data/:symbol/history', async () => {
      const params = { timeframe: '1D', limit: 100 };
      mockAxiosInstance.get.mockResolvedValue({ data: [] });

      await marketDataApi.getHistory('AAPL', params);

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/market-data/AAPL/history', { params });
    });

    it('getHistory with no params works', async () => {
      mockAxiosInstance.get.mockResolvedValue({ data: [] });

      await marketDataApi.getHistory('GOOGL');

      expect(mockAxiosInstance.get).toHaveBeenCalledWith('/market-data/GOOGL/history', { params: {} });
    });
  });

  describe('healthApi', () => {
    it('check calls GET /health', async () => {
      // healthApi uses axios.get directly, not the instance
      axios.get.mockResolvedValue({ data: { status: 'healthy' } });

      await healthApi.check();

      // Health endpoint is at root level, so it includes the full URL
      expect(axios.get).toHaveBeenCalledWith('http://localhost:8000/health');
    });
  });
});
