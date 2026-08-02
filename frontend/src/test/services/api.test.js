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
  let healthApi;
  let mockAxiosInstance;

  beforeEach(async () => {
    vi.resetModules();

    // Get mock axios instance
    mockAxiosInstance = axios.create();

    // Import the module fresh
    const apiModule = await import('../../services/api');
    healthApi = apiModule.healthApi;

    // Reset mocks
    mockAxiosInstance.get.mockReset();
    mockAxiosInstance.post.mockReset();
    mockAxiosInstance.put.mockReset();
    mockAxiosInstance.patch.mockReset();
    mockAxiosInstance.delete.mockReset();
    axios.get.mockReset();
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
