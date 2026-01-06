/**
 * Vitest test setup file
 */

import '@testing-library/jest-dom';

// Mock WebSocket globally
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.onopen = null;
    this.onclose = null;
    this.onmessage = null;
    this.onerror = null;

    // Simulate connection after a short delay
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      if (this.onopen) {
        this.onopen({ target: this });
      }
    }, 10);
  }

  send(data) {
    // Mock send - can be extended in tests
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose({ target: this });
    }
  }
}

global.WebSocket = MockWebSocket;

// Mock import.meta.env
if (typeof import.meta.env === 'undefined') {
  global.import = {
    meta: {
      env: {
        VITE_API_URL: 'http://localhost:8000',
        VITE_WS_URL: 'ws://localhost:8000',
      },
    },
  };
}

// Suppress console logs during tests (optional)
// Uncomment to silence console output
// global.console = {
//   ...console,
//   log: vi.fn(),
//   warn: vi.fn(),
//   error: vi.fn(),
// };
