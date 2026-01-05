import { Outlet, NavLink } from 'react-router-dom';
import { useEffect } from 'react';
import { useAppStore, useAlertsStore } from '../../store';
import useWebSocket from '../../hooks/useWebSocket';

const navItems = [
  { path: '/dashboard', label: 'Dashboard', icon: '📊' },
  { path: '/alerts', label: 'Alerts', icon: '🔔' },
  { path: '/rules', label: 'Rules', icon: '⚙️' },
  { path: '/settings', label: 'Settings', icon: '🔧' },
];

function Layout() {
  const { healthStatus, setConnected } = useAppStore();
  const { addAlert, fetchStats } = useAlertsStore();
  const { isConnected, lastMessage, subscribe } = useWebSocket();

  // Update connection state
  useEffect(() => {
    setConnected(isConnected);
  }, [isConnected, setConnected]);

  // Subscribe to alerts when connected
  useEffect(() => {
    if (isConnected) {
      subscribe('alerts');
    }
  }, [isConnected, subscribe]);

  // Handle incoming WebSocket messages
  useEffect(() => {
    if (lastMessage?.type === 'alert') {
      addAlert(lastMessage.data);
      fetchStats();
    }
  }, [lastMessage, addAlert, fetchStats]);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <h1 className="text-xl font-bold text-gray-900">
                Trading Alert Engine
              </h1>
            </div>

            {/* Connection Status */}
            <div className="flex items-center space-x-4">
              <div className="flex items-center space-x-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    isConnected ? 'bg-green-500' : 'bg-red-500'
                  }`}
                />
                <span className="text-sm text-gray-600">
                  {isConnected ? 'Connected' : 'Disconnected'}
                </span>
              </div>

              {healthStatus && (
                <div className="flex items-center space-x-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      healthStatus.status === 'healthy'
                        ? 'bg-green-500'
                        : healthStatus.status === 'degraded'
                        ? 'bg-yellow-500'
                        : 'bg-red-500'
                    }`}
                  />
                  <span className="text-sm text-gray-600">
                    API: {healthStatus.status}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Navigation */}
      <nav className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex space-x-8">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                    isActive
                      ? 'border-primary-500 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`
                }
              >
                <span className="mr-2">{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <p className="text-center text-sm text-gray-500">
            Trading Alert Engine v1.0.0 - Powered by Alpaca Markets
          </p>
        </div>
      </footer>
    </div>
  );
}

export default Layout;
