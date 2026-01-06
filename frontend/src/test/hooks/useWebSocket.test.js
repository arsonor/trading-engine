/**
 * Tests for useWebSocket hook
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// Store original WebSocket
const OriginalWebSocket = global.WebSocket;

describe('useWebSocket', () => {
  let mockWs;
  let wsInstances;

  beforeEach(() => {
    wsInstances = [];

    // Create a controllable mock WebSocket
    mockWs = vi.fn().mockImplementation((url) => {
      const instance = {
        url,
        readyState: 0, // CONNECTING
        onopen: null,
        onclose: null,
        onmessage: null,
        onerror: null,
        send: vi.fn(),
        close: vi.fn().mockImplementation(function() {
          this.readyState = 3; // CLOSED
          if (this.onclose) {
            this.onclose({ target: this });
          }
        }),
      };
      wsInstances.push(instance);
      return instance;
    });

    global.WebSocket = mockWs;
    global.WebSocket.CONNECTING = 0;
    global.WebSocket.OPEN = 1;
    global.WebSocket.CLOSING = 2;
    global.WebSocket.CLOSED = 3;
  });

  afterEach(() => {
    global.WebSocket = OriginalWebSocket;
    vi.resetModules();
  });

  it('initializes with disconnected state', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    expect(result.current.isConnected).toBe(false);
    expect(result.current.lastMessage).toBe(null);
    expect(result.current.subscriptions).toEqual([]);
  });

  it('connects automatically on mount', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    renderHook(() => useWebSocket());

    expect(mockWs).toHaveBeenCalled();
    expect(wsInstances.length).toBeGreaterThan(0);
  });

  it('updates isConnected when WebSocket opens', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Simulate WebSocket connection
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1; // OPEN
      if (ws.onopen) {
        ws.onopen({ target: ws });
      }
    });

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true);
    });
  });

  it('updates lastMessage when receiving messages', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Connect
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1;
      if (ws.onopen) ws.onopen({ target: ws });
    });

    // Receive message
    const testMessage = { type: 'test', data: { foo: 'bar' } };
    act(() => {
      const ws = wsInstances[0];
      if (ws.onmessage) {
        ws.onmessage({ data: JSON.stringify(testMessage) });
      }
    });

    await waitFor(() => {
      expect(result.current.lastMessage).toEqual(testMessage);
    });
  });

  it('updates subscriptions from status messages', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Connect
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1;
      if (ws.onopen) ws.onopen({ target: ws });
    });

    // Receive status message with subscriptions
    const statusMessage = {
      type: 'status',
      data: { subscriptions: ['alerts', 'market_data'] },
    };
    act(() => {
      const ws = wsInstances[0];
      if (ws.onmessage) {
        ws.onmessage({ data: JSON.stringify(statusMessage) });
      }
    });

    await waitFor(() => {
      expect(result.current.subscriptions).toEqual(['alerts', 'market_data']);
    });
  });

  it('sendMessage sends JSON to WebSocket', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Connect
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1;
      if (ws.onopen) ws.onopen({ target: ws });
    });

    // Send message
    const message = { action: 'test' };
    act(() => {
      result.current.sendMessage(message);
    });

    expect(wsInstances[0].send).toHaveBeenCalledWith(JSON.stringify(message));
  });

  it('subscribe sends subscribe action', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Connect
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1;
      if (ws.onopen) ws.onopen({ target: ws });
    });

    // Subscribe to channel
    act(() => {
      result.current.subscribe('alerts');
    });

    expect(wsInstances[0].send).toHaveBeenCalledWith(
      JSON.stringify({ action: 'subscribe', channel: 'alerts' })
    );
  });

  it('subscribe with symbols includes symbols in message', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Connect
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1;
      if (ws.onopen) ws.onopen({ target: ws });
    });

    // Subscribe with symbols
    act(() => {
      result.current.subscribe('market_data', ['AAPL', 'GOOGL']);
    });

    expect(wsInstances[0].send).toHaveBeenCalledWith(
      JSON.stringify({
        action: 'subscribe',
        channel: 'market_data',
        symbols: ['AAPL', 'GOOGL'],
      })
    );
  });

  it('unsubscribe sends unsubscribe action', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Connect
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1;
      if (ws.onopen) ws.onopen({ target: ws });
    });

    // Unsubscribe
    act(() => {
      result.current.unsubscribe('alerts');
    });

    expect(wsInstances[0].send).toHaveBeenCalledWith(
      JSON.stringify({ action: 'unsubscribe', channel: 'alerts' })
    );
  });

  it('disconnect closes WebSocket', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Connect
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1;
      if (ws.onopen) ws.onopen({ target: ws });
    });

    // Disconnect
    act(() => {
      result.current.disconnect();
    });

    expect(wsInstances[0].close).toHaveBeenCalled();
  });

  it('does not send messages when disconnected', async () => {
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Don't connect, WebSocket stays in CONNECTING state

    // Try to send message
    act(() => {
      result.current.sendMessage({ action: 'test' });
    });

    expect(wsInstances[0].send).not.toHaveBeenCalled();
  });

  it('handles JSON parse errors gracefully', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { useWebSocket } = await import('../../hooks/useWebSocket');

    const { result } = renderHook(() => useWebSocket());

    // Connect
    act(() => {
      const ws = wsInstances[0];
      ws.readyState = 1;
      if (ws.onopen) ws.onopen({ target: ws });
    });

    // Receive invalid JSON
    act(() => {
      const ws = wsInstances[0];
      if (ws.onmessage) {
        ws.onmessage({ data: 'not valid json' });
      }
    });

    expect(consoleSpy).toHaveBeenCalled();
    expect(result.current.lastMessage).toBe(null);

    consoleSpy.mockRestore();
  });
});
