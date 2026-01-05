import { useEffect } from 'react';
import { useAlertsStore, useWatchlistStore, useRulesStore } from '../store';
import { format } from 'date-fns';

function DashboardPage() {
  const { alerts, stats, fetchAlerts, fetchStats } = useAlertsStore();
  const { items: watchlist, fetchWatchlist } = useWatchlistStore();
  const { rules, fetchRules } = useRulesStore();

  useEffect(() => {
    fetchAlerts();
    fetchStats();
    fetchWatchlist();
    fetchRules();
  }, [fetchAlerts, fetchStats, fetchWatchlist, fetchRules]);

  const recentAlerts = alerts.slice(0, 5);
  const activeRules = rules.filter((r) => r.is_active).length;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">Dashboard</h2>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-sm font-medium text-gray-500">Alerts Today</div>
          <div className="mt-1 text-3xl font-semibold text-gray-900">
            {stats?.alerts_today ?? '-'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm font-medium text-gray-500">Unread Alerts</div>
          <div className="mt-1 text-3xl font-semibold text-primary-600">
            {stats?.unread_count ?? '-'}
          </div>
        </div>
        <div className="card">
          <div className="text-sm font-medium text-gray-500">Active Rules</div>
          <div className="mt-1 text-3xl font-semibold text-gray-900">
            {activeRules}
          </div>
        </div>
        <div className="card">
          <div className="text-sm font-medium text-gray-500">Watchlist</div>
          <div className="mt-1 text-3xl font-semibold text-gray-900">
            {watchlist.length}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Alerts */}
        <div className="card">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Recent Alerts</h3>
          {recentAlerts.length === 0 ? (
            <p className="text-gray-500">No alerts yet</p>
          ) : (
            <div className="space-y-3">
              {recentAlerts.map((alert) => (
                <div
                  key={alert.id}
                  className={`alert-card ${
                    alert.setup_type === 'breakout' || alert.setup_type === 'gap_up'
                      ? 'alert-card-buy'
                      : 'alert-card-sell'
                  }`}
                >
                  <div className="flex justify-between items-start">
                    <div>
                      <span className="font-semibold text-gray-900">
                        {alert.symbol}
                      </span>
                      <span className="ml-2 text-sm text-gray-500">
                        {alert.setup_type}
                      </span>
                    </div>
                    <span className="text-sm text-gray-500">
                      {format(new Date(alert.timestamp), 'HH:mm:ss')}
                    </span>
                  </div>
                  <div className="mt-1 text-sm">
                    <span className="text-gray-600">Entry: </span>
                    <span className="font-medium">${alert.entry_price.toFixed(2)}</span>
                    {alert.stop_loss && (
                      <>
                        <span className="ml-3 text-gray-600">SL: </span>
                        <span className="text-danger-500">
                          ${alert.stop_loss.toFixed(2)}
                        </span>
                      </>
                    )}
                    {alert.target_price && (
                      <>
                        <span className="ml-3 text-gray-600">TP: </span>
                        <span className="text-success-500">
                          ${alert.target_price.toFixed(2)}
                        </span>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Setup Type Distribution */}
        <div className="card">
          <h3 className="text-lg font-medium text-gray-900 mb-4">
            Alert Distribution
          </h3>
          {stats?.by_setup_type ? (
            <div className="space-y-3">
              {Object.entries(stats.by_setup_type).map(([type, count]) => (
                <div key={type} className="flex items-center">
                  <div className="w-24 text-sm text-gray-600">{type}</div>
                  <div className="flex-1 mx-4">
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div
                        className="bg-primary-500 h-2 rounded-full"
                        style={{
                          width: `${(count / stats.total_alerts) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                  <div className="w-12 text-right text-sm font-medium">
                    {count}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500">No data available</p>
          )}
        </div>

        {/* Watchlist */}
        <div className="card">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Watchlist</h3>
          {watchlist.length === 0 ? (
            <p className="text-gray-500">No symbols in watchlist</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {watchlist.map((item) => (
                <span
                  key={item.id}
                  className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-800"
                >
                  {item.symbol}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Active Rules */}
        <div className="card">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Active Rules</h3>
          {rules.length === 0 ? (
            <p className="text-gray-500">No rules configured</p>
          ) : (
            <div className="space-y-2">
              {rules
                .filter((r) => r.is_active)
                .slice(0, 5)
                .map((rule) => (
                  <div
                    key={rule.id}
                    className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0"
                  >
                    <div>
                      <span className="font-medium text-gray-900">
                        {rule.name}
                      </span>
                      <span className="ml-2 text-xs text-gray-500">
                        {rule.rule_type}
                      </span>
                    </div>
                    <span className="text-sm text-gray-500">
                      {rule.alerts_triggered} alerts
                    </span>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default DashboardPage;
