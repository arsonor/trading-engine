/**
 * Tests for API service
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
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
  let watchlistApi;
  let healthApi;
  let mockAxiosInstance;

  beforeEach(async () => {
    vi.resetModules();

    // Get mock axios instance
    mockAxiosInstance = axios.create();

    // Import the module fresh
    const apiModule = await import('../../services/api');
    watchlistApi = apiModule.watchlistApi;
    healthApi = apiModule.healthApi;

    // Reset mocks
    mockAxiosInstance.get.mockReset();
    mockAxiosInstance.post.mockReset();
    mockAxiosInstance.put.mockReset();
    mockAxiosInstance.patch.mockReset();
    mockAxiosInstance.delete.mockReset();
    axios.get.mockReset();
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
