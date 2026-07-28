/**
 * Threshold settings.
 *
 * Edits persist to the database and take effect on the **next scan** — no redeploy.
 * That is a product requirement, not a convenience: the end user's strategy will
 * evolve, and a deploy cycle is not an acceptable price for changing a number.
 *
 * Only fields the user has actually touched are pinned. Everything else keeps following
 * the environment defaults, so a later change to a default still reaches them.
 */

import { useEffect, useState } from 'react';
import { useScannerStore } from '../store';

const FIELDS = [
  {
    key: 'float_max',
    label: 'Max float (shares)',
    step: 1000000,
    help: 'Stage 1 — smaller floats move further on the same volume.',
  },
  {
    key: 'avg_volume_min',
    label: 'Min 20-day avg volume',
    step: 50000,
    help: 'Stage 1 — filters out names too thin to trade.',
  },
  { key: 'gap_min', label: 'Min gap %', step: 0.1, help: 'Stage 2 — below this is noise.' },
  {
    key: 'gap_max',
    label: 'Max gap %',
    step: 0.1,
    help: 'Stage 2 — above this the move is largely spent.',
  },
  {
    key: 'rvol_min',
    label: 'Min RVOL %',
    step: 0.5,
    help: 'Stage 2 — volume conviction behind the gap.',
  },
  {
    key: 'upside_min',
    label: 'Min upside %',
    step: 0.1,
    help: 'Stage 3 — 5% target plus a 0.5% slippage buffer.',
  },
  { key: 'price_floor', label: 'Min price ($)', step: 0.5, help: 'Risk filter — sub-$2 names hit 5% on noise.' },
  {
    key: 'dollar_volume_min',
    label: 'Min dollar volume ($)',
    step: 100000,
    help: 'Risk filter — can the position be traded in size.',
  },
];

export default function SettingsPage() {
  const { settings, settingsSaving, settingsError, fetchSettings, saveSettings, resetSettings } =
    useScannerStore();
  const [form, setForm] = useState({});
  const [saved, setSaved] = useState(false);
  const [syncedSettings, setSyncedSettings] = useState(null);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  // Seed the form from the server's canonical settings, and re-seed whenever they
  // change (initial load, or after a save returns the effective values). This is
  // React's render-phase adjustment pattern rather than an effect: setState inside an
  // effect would render once with a stale form and then again with the real one.
  if (settings && settings !== syncedSettings) {
    setSyncedSettings(settings);
    setForm(
      FIELDS.reduce((acc, f) => ({ ...acc, [f.key]: settings[f.key] }), {
        profile: settings.profile,
      })
    );
  }

  const handleChange = (key, value) => {
    setSaved(false);
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSaved(false);
    const payload = { profile: form.profile };
    FIELDS.forEach((f) => {
      const value = form[f.key];
      if (value !== '' && value != null) payload[f.key] = Number(value);
    });
    try {
      await saveSettings(payload);
      setSaved(true);
    } catch {
      /* error surfaces via settingsError */
    }
  };

  const handleReset = async () => {
    setSaved(false);
    await resetSettings();
  };

  if (!settings) {
    return <p className="text-sm text-slate-500">Loading settings…</p>;
  }

  const pinned = Object.keys(settings.overrides ?? {});

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-bold text-slate-900">Scanner thresholds</h1>
        <p className="text-xs leading-snug text-slate-500">
          Changes are saved to the database and apply to the <strong>next scan</strong>. No
          redeploy needed.
        </p>
      </header>

      {settings.is_demo && (
        <div className="rounded-lg border-2 border-amber-400 bg-amber-50 p-3 text-xs leading-snug text-amber-900">
          <strong className="font-bold">Demo profile active.</strong> {settings.description}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <label htmlFor="profile" className="block text-sm font-medium text-slate-800">
            Threshold profile
          </label>
          <select
            id="profile"
            value={form.profile ?? 'production'}
            onChange={(e) => handleChange('profile', e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="production">production — the real specification</option>
            <option value="demo">demo — loosened float cap, illustrative only</option>
          </select>
          <p className="mt-1 text-xs text-slate-500">
            Demo loosens only the float cap so free-tier mega-caps can reach Stage 1. Every
            other threshold stays at its production value.
          </p>
        </div>

        <div className="space-y-3">
          {FIELDS.map((field) => (
            <div key={field.key} className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="flex items-baseline justify-between gap-2">
                <label
                  htmlFor={field.key}
                  className="text-sm font-medium text-slate-800"
                >
                  {field.label}
                </label>
                {pinned.includes(field.key) && (
                  <span className="rounded bg-primary-100 px-1.5 py-0.5 text-[10px] font-semibold text-primary-700">
                    pinned
                  </span>
                )}
              </div>
              <input
                id={field.key}
                type="number"
                step={field.step}
                min="0"
                value={form[field.key] ?? ''}
                onChange={(e) => handleChange(field.key, e.target.value)}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
              <p className="mt-1 text-xs leading-snug text-slate-500">{field.help}</p>
            </div>
          ))}
        </div>

        {settingsError && (
          <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900">
            {settingsError}
          </div>
        )}
        {saved && (
          <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900">
            Saved. These thresholds apply to the next scan.
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={settingsSaving}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {settingsSaving ? 'Saving…' : 'Save thresholds'}
          </button>
          <button
            type="button"
            onClick={handleReset}
            disabled={settingsSaving}
            className="rounded-lg bg-slate-200 px-4 py-2 text-sm font-medium text-slate-800 disabled:opacity-50"
          >
            Reset to defaults
          </button>
        </div>
      </form>
    </div>
  );
}
