/**
 * API client for Trading Engine backend
 */

import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for logging
api.interceptors.request.use(
  (config) => {
    console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`);
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('[API Error]', error.response?.data || error.message);
    return Promise.reject(error);
  }
);

// Alerts API
export const alertsApi = {
  list: (params = {}) => api.get('/alerts', { params }),
  get: (id) => api.get(`/alerts/${id}`),
  update: (id, data) => api.patch(`/alerts/${id}`, data),
  getStats: () => api.get('/alerts/stats'),
};

// Rules API
export const rulesApi = {
  list: () => api.get('/rules'),
  get: (id) => api.get(`/rules/${id}`),
  create: (data) => api.post('/rules', data),
  update: (id, data) => api.put(`/rules/${id}`, data),
  delete: (id) => api.delete(`/rules/${id}`),
  toggle: (id) => api.post(`/rules/${id}/toggle`),
};

// Watchlist API
export const watchlistApi = {
  list: () => api.get('/watchlist'),
  add: (data) => api.post('/watchlist', data),
  remove: (symbol) => api.delete(`/watchlist/${symbol}`),
};

// Market Data API
export const marketDataApi = {
  get: (symbol) => api.get(`/market-data/${symbol}`),
  getHistory: (symbol, params = {}) => api.get(`/market-data/${symbol}/history`, { params }),
};

// Health API
export const healthApi = {
  check: () => api.get('/health'),
};

export default api;
