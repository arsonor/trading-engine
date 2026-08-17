/**
 * Global state management with Zustand
 */

import { create } from 'zustand';
import { healthApi, scannerApi } from '../services/api';

/**
 * Scanner store (v2) — session alerts, scan status and tunable thresholds.
 *
 * `status.state` is the field that keeps "the market was quiet" and "the scanner is
 * broken" apart. Never collapse them into an empty-list check: an empty list is a
 * legitimate, frequent, healthy outcome, and rendering it the same as an outage is how
 * a user stops trusting the tool at the exact moment it stops working.
 */
export const useScannerStore = create((set, get) => ({
  alerts: [],
  sessionDate: null,
  hasDemoAlerts: false,
  status: null,
  scanRuns: [],
  settings: null,
  loading: false,
  settingsSaving: false,
  error: null,
  settingsError: null,

  fetchAlerts: async (params = {}) => {
    set({ loading: true, error: null });
    try {
      const { data } = await scannerApi.listAlerts(params);
      set({
        alerts: data.items,
        sessionDate: data.session_date,
        hasDemoAlerts: data.has_demo_alerts,
        loading: false,
      });
    } catch (error) {
      set({ error: error.message, loading: false });
    }
  },

  fetchStatus: async () => {
    try {
      const { data } = await scannerApi.getStatus();
      set({ status: data });
    } catch (error) {
      // A status fetch that fails is itself a degraded state — surface it rather than
      // leaving the panel showing the last good value.
      set({ status: { state: 'unknown', is_healthy: false, detail: error.message } });
    }
  },

  // `attemptedOnly` defaults to true because of the tiered cadence: 65 of a weekday's 84
  // cron wake-ups are skipped heartbeats, so an unfiltered page of 20 rows shows nothing
  // but heartbeats for most of the day and the scan history stops being a scan history.
  // "Did the cron fire?" is answered by `status.last_wake_up_at` instead.
  fetchScanRuns: async (limit = 20, attemptedOnly = true) => {
    try {
      const { data } = await scannerApi.listScanRuns({
        limit,
        attempted_only: attemptedOnly,
      });
      set({ scanRuns: data });
    } catch (error) {
      set({ error: error.message });
    }
  },

  fetchSettings: async () => {
    try {
      const { data } = await scannerApi.getSettings();
      set({ settings: data, settingsError: null });
    } catch (error) {
      set({ settingsError: error.message });
    }
  },

  saveSettings: async (payload) => {
    set({ settingsSaving: true, settingsError: null });
    try {
      const { data } = await scannerApi.updateSettings(payload);
      set({ settings: data, settingsSaving: false });
      return data;
    } catch (error) {
      const detail = error.response?.data?.detail || error.message;
      set({ settingsError: detail, settingsSaving: false });
      throw error;
    }
  },

  resetSettings: async () => {
    set({ settingsSaving: true, settingsError: null });
    try {
      const { data } = await scannerApi.resetSettings();
      set({ settings: data, settingsSaving: false });
      return data;
    } catch (error) {
      set({ settingsError: error.message, settingsSaving: false });
      throw error;
    }
  },

  markRead: async (alertId) => {
    try {
      await scannerApi.markRead(alertId);
      set((state) => ({
        alerts: state.alerts.map((a) => (a.id === alertId ? { ...a, is_read: true } : a)),
      }));
    } catch (error) {
      console.error('Failed to mark alert read:', error);
    }
  },

  /** Replace the session's alerts from a `scan_alerts` WebSocket push. */
  applyScanBroadcast: (payload) => {
    if (!payload?.alerts) return;
    set({
      alerts: payload.alerts,
      sessionDate: payload.session_date ?? get().sessionDate,
      hasDemoAlerts: payload.alerts.some((a) => a.is_demo),
    });
  },
}));

// App state store
export const useAppStore = create((set) => ({
  isConnected: false,
  healthStatus: null,

  setConnected: (isConnected) => set({ isConnected }),

  checkHealth: async () => {
    try {
      const response = await healthApi.check();
      set({ healthStatus: response.data });
    } catch {
      set({ healthStatus: { status: 'unhealthy' } });
    }
  },
}));
