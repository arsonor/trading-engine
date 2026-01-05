import { useEffect, useState } from 'react';
import { useAlertsStore } from '../store';
import { format } from 'date-fns';

function AlertsPage() {
  const {
    alerts,
    loading,
    filters,
    pagination,
    setFilters,
    fetchAlerts,
    markAsRead,
    setPage,
  } = useAlertsStore();

  const [searchSymbol, setSearchSymbol] = useState(filters.symbol);

  useEffect(() => {
    fetchAlerts();
  }, [filters, fetchAlerts]);

  const handleSearch = (e) => {
    e.preventDefault();
    setFilters({ symbol: searchSymbol.toUpperCase() });
  };

  const handleSetupTypeFilter = (setupType) => {
    setFilters({ setup_type: setupType === filters.setup_type ? '' : setupType });
  };

  const handleReadFilter = (isRead) => {
    setFilters({ is_read: filters.is_read === isRead ? null : isRead });
  };

  const setupTypes = ['breakout', 'volume_spike', 'gap_up', 'gap_down', 'momentum'];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold text-gray-900">Alerts</h2>
        <span className="text-sm text-gray-500">
          Total: {pagination.total} alerts
        </span>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-4 items-center">
          {/* Search by symbol */}
          <form onSubmit={handleSearch} className="flex items-center">
            <input
              type="text"
              value={searchSymbol}
              onChange={(e) => setSearchSymbol(e.target.value)}
              placeholder="Search symbol..."
              className="input w-40"
            />
            <button type="submit" className="ml-2 btn btn-primary">
              Search
            </button>
          </form>

          {/* Setup type filter */}
          <div className="flex items-center space-x-2">
            <span className="text-sm text-gray-500">Type:</span>
            {setupTypes.map((type) => (
              <button
                key={type}
                onClick={() => handleSetupTypeFilter(type)}
                className={`px-3 py-1 rounded-full text-sm ${
                  filters.setup_type === type
                    ? 'bg-primary-500 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {type}
              </button>
            ))}
          </div>

          {/* Read filter */}
          <div className="flex items-center space-x-2">
            <span className="text-sm text-gray-500">Status:</span>
            <button
              onClick={() => handleReadFilter(false)}
              className={`px-3 py-1 rounded-full text-sm ${
                filters.is_read === false
                  ? 'bg-primary-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              Unread
            </button>
            <button
              onClick={() => handleReadFilter(true)}
              className={`px-3 py-1 rounded-full text-sm ${
                filters.is_read === true
                  ? 'bg-primary-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              Read
            </button>
          </div>

          {/* Clear filters */}
          <button
            onClick={() => {
              setSearchSymbol('');
              setFilters({
                symbol: '',
                setup_type: '',
                is_read: null,
              });
            }}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear filters
          </button>
        </div>
      </div>

      {/* Alerts List */}
      <div className="space-y-3">
        {loading ? (
          <div className="text-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500 mx-auto"></div>
            <p className="mt-2 text-gray-500">Loading alerts...</p>
          </div>
        ) : alerts.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-gray-500">No alerts found</p>
          </div>
        ) : (
          alerts.map((alert) => (
            <div
              key={alert.id}
              className={`card cursor-pointer hover:shadow-md transition-shadow ${
                !alert.is_read ? 'border-l-4 border-l-primary-500' : ''
              }`}
              onClick={() => !alert.is_read && markAsRead(alert.id)}
            >
              <div className="flex justify-between items-start">
                <div className="flex items-center space-x-3">
                  <span className="text-xl font-bold text-gray-900">
                    {alert.symbol}
                  </span>
                  <span
                    className={`status-badge ${
                      alert.setup_type === 'breakout' || alert.setup_type === 'gap_up'
                        ? 'bg-green-100 text-green-800'
                        : alert.setup_type === 'gap_down'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-blue-100 text-blue-800'
                    }`}
                  >
                    {alert.setup_type}
                  </span>
                  {!alert.is_read && (
                    <span className="status-badge status-badge-unread">New</span>
                  )}
                </div>
                <div className="text-right">
                  <div className="text-sm text-gray-500">
                    {format(new Date(alert.timestamp), 'MMM d, yyyy HH:mm:ss')}
                  </div>
                  {alert.confidence_score && (
                    <div className="text-sm text-gray-500">
                      Confidence: {(alert.confidence_score * 100).toFixed(0)}%
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-3 grid grid-cols-3 gap-4">
                <div>
                  <span className="text-sm text-gray-500">Entry Price</span>
                  <div className="text-lg font-semibold">
                    ${alert.entry_price.toFixed(2)}
                  </div>
                </div>
                <div>
                  <span className="text-sm text-gray-500">Stop Loss</span>
                  <div className="text-lg font-semibold text-danger-500">
                    {alert.stop_loss ? `$${alert.stop_loss.toFixed(2)}` : '-'}
                  </div>
                </div>
                <div>
                  <span className="text-sm text-gray-500">Target</span>
                  <div className="text-lg font-semibold text-success-500">
                    {alert.target_price ? `$${alert.target_price.toFixed(2)}` : '-'}
                  </div>
                </div>
              </div>

              {alert.rule_name && (
                <div className="mt-2 text-sm text-gray-500">
                  Rule: {alert.rule_name}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Pagination */}
      {pagination.total > pagination.page_size && (
        <div className="flex justify-center items-center space-x-4">
          <button
            onClick={() => setPage(pagination.page - 1)}
            disabled={!pagination.has_prev}
            className="btn btn-secondary disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-sm text-gray-500">
            Page {pagination.page} of{' '}
            {Math.ceil(pagination.total / pagination.page_size)}
          </span>
          <button
            onClick={() => setPage(pagination.page + 1)}
            disabled={!pagination.has_next}
            className="btn btn-secondary disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

export default AlertsPage;
