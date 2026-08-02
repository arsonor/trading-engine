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

// Scanner API (v2) — the pre-market scanner.
export const scannerApi = {
  // Session alerts, strongest confidence first. Omit sessionDate for the latest session.
  listAlerts: (params = {}) => api.get('/scanner/alerts', { params }),
  getAlert: (id) => api.get(`/scanner/alerts/${id}`),
  markRead: (id) => api.post(`/scanner/alerts/${id}/read`),
  // Distinguishes a quiet market from a broken scanner — see `state`.
  getStatus: () => api.get('/scanner/status'),
  listScanRuns: (params = {}) => api.get('/scanner/scan-runs', { params }),
  getSettings: () => api.get('/scanner/settings'),
  updateSettings: (data) => api.put('/scanner/settings', data),
  resetSettings: () => api.delete('/scanner/settings'),
};

// Health API (health endpoint is at root level, not under /api/v1)
export const healthApi = {
  check: () => axios.get(`${API_BASE_URL}/health`),
};

export default api;
