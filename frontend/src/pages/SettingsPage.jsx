import { useEffect, useState } from 'react';
import { useWatchlistStore, useAppStore } from '../store';

function SettingsPage() {
  const { items: watchlist, fetchWatchlist, addSymbol, removeSymbol } =
    useWatchlistStore();
  const { healthStatus } = useAppStore();

  const [newSymbol, setNewSymbol] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    fetchWatchlist();
  }, [fetchWatchlist]);

  const handleAddSymbol = async (e) => {
    e.preventDefault();
    setError('');

    if (!newSymbol.trim()) {
      setError('Please enter a symbol');
      return;
    }

    try {
      await addSymbol(newSymbol.trim(), notes.trim());
      setNewSymbol('');
      setNotes('');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to add symbol');
    }
  };

  const handleRemoveSymbol = async (symbol) => {
    if (window.confirm(`Remove ${symbol} from watchlist?`)) {
      try {
        await removeSymbol(symbol);
      } catch (err) {
        setError(err.response?.data?.detail || 'Failed to remove symbol');
      }
    }
  };

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">Settings</h2>

      {/* Watchlist Management */}
      <div className="card">
        <h3 className="text-lg font-medium text-gray-900 mb-4">
          Watchlist Management
        </h3>

        {/* Add Symbol Form */}
        <form onSubmit={handleAddSymbol} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="label">Symbol</label>
              <input
                type="text"
                value={newSymbol}
                onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                placeholder="AAPL"
                className="input"
              />
            </div>
            <div className="md:col-span-2">
              <label className="label">Notes (optional)</label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Watch for earnings..."
                className="input"
              />
            </div>
          </div>
          {error && <p className="text-sm text-danger-500">{error}</p>}
          <button type="submit" className="btn btn-primary">
            Add to Watchlist
          </button>
        </form>

        {/* Current Watchlist */}
        <div className="mt-6">
          <h4 className="text-sm font-medium text-gray-700 mb-3">
            Current Watchlist ({watchlist.length} symbols)
          </h4>
          {watchlist.length === 0 ? (
            <p className="text-gray-500">No symbols in watchlist</p>
          ) : (
            <div className="space-y-2">
              {watchlist.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center justify-between py-2 px-3 bg-gray-50 rounded-lg"
                >
                  <div>
                    <span className="font-medium text-gray-900">
                      {item.symbol}
                    </span>
                    {item.notes && (
                      <span className="ml-3 text-sm text-gray-500">
                        {item.notes}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => handleRemoveSymbol(item.symbol)}
                    className="text-sm text-danger-500 hover:text-danger-600"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* System Status */}
      <div className="card">
        <h3 className="text-lg font-medium text-gray-900 mb-4">System Status</h3>
        <div className="space-y-3">
          <div className="flex items-center justify-between py-2 border-b border-gray-100">
            <span className="text-gray-600">API Status</span>
            <span
              className={`status-badge ${
                healthStatus?.status === 'healthy'
                  ? 'status-badge-active'
                  : 'status-badge-inactive'
              }`}
            >
              {healthStatus?.status || 'Unknown'}
            </span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-gray-100">
            <span className="text-gray-600">Database</span>
            <span
              className={`status-badge ${
                healthStatus?.database_connected
                  ? 'status-badge-active'
                  : 'status-badge-inactive'
              }`}
            >
              {healthStatus?.database_connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-gray-100">
            <span className="text-gray-600">Alpaca API</span>
            <span
              className={`status-badge ${
                healthStatus?.alpaca_connected
                  ? 'status-badge-active'
                  : 'status-badge-inactive'
              }`}
            >
              {healthStatus?.alpaca_connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
          <div className="flex items-center justify-between py-2">
            <span className="text-gray-600">Version</span>
            <span className="text-gray-900">
              {healthStatus?.version || '1.0.0'}
            </span>
          </div>
        </div>
      </div>

      {/* API Configuration Info */}
      <div className="card bg-yellow-50 border-yellow-200">
        <h3 className="text-sm font-medium text-yellow-800">
          API Configuration
        </h3>
        <p className="mt-1 text-sm text-yellow-700">
          Alpaca API credentials are configured via environment variables on the
          server. Set <code>ALPACA_API_KEY</code> and{' '}
          <code>ALPACA_SECRET_KEY</code> in your <code>.env</code> file.
        </p>
      </div>
    </div>
  );
}

export default SettingsPage;
