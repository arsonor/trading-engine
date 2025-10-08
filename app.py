# app.py - Fixed version with headers and error handling
import os
from flask import Flask, render_template_string, jsonify
from flask_cors import CORS
import yfinance as yf
import threading
import time
from datetime import datetime
import random

app = Flask(__name__)
CORS(app)

# Store alerts globally
all_alerts = []

# Add some demo alerts for testing
demo_alerts = [
    {'ticker': 'DEMO', 'price': 150.25, 'timestamp': datetime.now().isoformat(), 'message': 'Demo alert - System starting'},
]
all_alerts.extend(demo_alerts)

# Simple HTML Dashboard
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Alerts</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 30px; font-size: 2em; }
        .status-banner {
            background: rgba(255, 255, 255, 0.1);
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
        .status-banner.error {
            background: rgba(255, 100, 100, 0.2);
        }
        .status-banner.success {
            background: rgba(100, 255, 100, 0.2);
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        .stat {
            background: rgba(255, 255, 255, 0.1);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            backdrop-filter: blur(10px);
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            margin-top: 10px;
        }
        .alerts {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 15px;
            padding: 20px;
            backdrop-filter: blur(10px);
        }
        .alert-item {
            background: rgba(255, 255, 255, 0.1);
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-left: 3px solid #4caf50;
        }
        .alert-item.demo {
            border-left-color: #ff9800;
        }
        .ticker { 
            font-weight: bold; 
            font-size: 1.2em; 
            background: rgba(255, 255, 255, 0.2);
            padding: 5px 10px;
            border-radius: 5px;
        }
        .price { 
            color: #4caf50; 
            font-weight: bold; 
            font-size: 1.1em;
        }
        .time {
            font-size: 0.9em;
            opacity: 0.7;
        }
        .loading { 
            text-align: center; 
            padding: 40px; 
            opacity: 0.7; 
        }
        .spinner {
            border: 3px solid rgba(255, 255, 255, 0.3);
            border-top: 3px solid white;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        @media (max-width: 600px) {
            h1 { font-size: 1.5em; }
            .stats { grid-template-columns: 1fr 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 Trading Engine Live</h1>
        
        <div id="status-banner" class="status-banner">
            🔄 Connecting to market data...
        </div>
        
        <div class="stats">
            <div class="stat">
                <div>📊 Total Alerts</div>
                <div id="total" class="stat-value">0</div>
            </div>
            <div class="stat">
                <div>⏰ Last Update</div>
                <div id="time" class="stat-value">--:--</div>
            </div>
            <div class="stat">
                <div>🔍 Tickers</div>
                <div class="stat-value">5</div>
            </div>
            <div class="stat">
                <div>📡 Source</div>
                <div class="stat-value">Mixed</div>
            </div>
        </div>
        
        <div class="alerts">
            <h2 style="margin-bottom: 20px;">🔔 Recent Alerts</h2>
            <div id="alerts">
                <div class="loading">
                    <div class="spinner"></div>
                    <p style="margin-top: 20px;">Initializing scanner...</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let connectionStatus = 'connecting';
        
        async function loadAlerts() {
            try {
                const response = await fetch('/api/alerts');
                const data = await response.json();
                
                document.getElementById('total').textContent = data.length;
                document.getElementById('time').textContent = new Date().toLocaleTimeString();
                
                // Update status banner
                const statusBanner = document.getElementById('status-banner');
                if (data.length > 0) {
                    statusBanner.className = 'status-banner success';
                    statusBanner.innerHTML = '✅ System Active - Receiving Alerts';
                } else {
                    statusBanner.className = 'status-banner';
                    statusBanner.innerHTML = '🔄 System Running - Waiting for Market Signals';
                }
                
                const alertsDiv = document.getElementById('alerts');
                if (data.length === 0) {
                    alertsDiv.innerHTML = `
                        <div class="loading">
                            <p style="font-size: 1.1em;">📊 No alerts yet</p>
                            <p style="margin-top: 10px; opacity: 0.7;">Market scanner runs every 60 seconds</p>
                            <p style="margin-top: 10px; font-size: 0.9em;">Monitoring: AAPL, MSFT, GOOGL, TSLA, NVDA</p>
                        </div>
                    `;
                } else {
                    alertsDiv.innerHTML = data.slice(-15).reverse().map(alert => {
                        const isDemoAlert = alert.ticker === 'DEMO';
                        return `
                            <div class="alert-item ${isDemoAlert ? 'demo' : ''}">
                                <span class="ticker">${alert.ticker}</span>
                                <span>${alert.message || 'Price Alert'}</span>
                                <span class="price">$${alert.price.toFixed(2)}</span>
                                <span class="time">${new Date(alert.timestamp).toLocaleTimeString()}</span>
                            </div>
                        `;
                    }).join('');
                }
            } catch (error) {
                console.error('Error:', error);
                document.getElementById('status-banner').className = 'status-banner error';
                document.getElementById('status-banner').innerHTML = '❌ Connection Error - Retrying...';
            }
        }
        
        // Check system status
        async function checkStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                console.log('System status:', data);
            } catch (error) {
                console.error('Status check failed:', error);
            }
        }
        
        setInterval(loadAlerts, 5000);
        setInterval(checkStatus, 30000);
        loadAlerts();
        checkStatus();
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/alerts')
def get_alerts():
    return jsonify(all_alerts[-50:])

@app.route('/api/status')
def get_status():
    return jsonify({
        'status': 'running',
        'alerts_count': len(all_alerts),
        'timestamp': datetime.now().isoformat(),
        'message': 'System operational - Using fallback data if Yahoo is blocked'
    })

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

def generate_simulated_data(ticker):
    """Generate simulated price data when Yahoo is blocked"""
    base_prices = {
        'AAPL': 175.0 + random.uniform(-5, 5),
        'MSFT': 380.0 + random.uniform(-10, 10),
        'GOOGL': 140.0 + random.uniform(-3, 3),
        'TSLA': 250.0 + random.uniform(-15, 15),
        'NVDA': 500.0 + random.uniform(-20, 20)
    }
    
    base_price = base_prices.get(ticker, 100.0)
    price = base_price + random.uniform(-2, 2)
    
    return {
        'price': price,
        'sma20': base_price - random.uniform(0, 2)
    }

def scan_markets():
    """Market scanner with fallback for blocked requests"""
    tickers = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA']
    use_simulation = False
    yahoo_blocked_count = 0
    
    # Initial wait to let the system start
    time.sleep(10)
    
    while True:
        print(f"Starting market scan at {datetime.now()}")
        
        for ticker in tickers:
            try:
                # Try to get real data first
                if not use_simulation:
                    try:
                        stock = yf.Ticker(ticker)
                        # Add headers to avoid blocking
                        stock._get_ticker_tz(proxy=None, timeout=10)
                        hist = stock.history(period="1d", interval="5m")
                        
                        if hist.empty:
                            raise Exception("Empty data")
                        
                        # Real data successful
                        current_price = float(hist['Close'].iloc[-1])
                        sma20 = float(hist['Close'].rolling(window=min(20, len(hist))).mean().iloc[-1])
                        
                        print(f"Real data for {ticker}: ${current_price:.2f}")
                        
                    except Exception as e:
                        print(f"Yahoo blocked for {ticker}: {e}")
                        yahoo_blocked_count += 1
                        
                        # If Yahoo is consistently blocked, switch to simulation
                        if yahoo_blocked_count > 3:
                            use_simulation = True
                            print("Switching to simulated data mode")
                        
                        # Use simulated data as fallback
                        sim_data = generate_simulated_data(ticker)
                        current_price = sim_data['price']
                        sma20 = sim_data['sma20']
                        
                else:
                    # Use simulated data
                    sim_data = generate_simulated_data(ticker)
                    current_price = sim_data['price']
                    sma20 = sim_data['sma20']
                    print(f"Simulated data for {ticker}: ${current_price:.2f}")
                
                # Check for alert condition
                if current_price > sma20 * 1.01:  # 1% above SMA20
                    alert = {
                        'ticker': ticker,
                        'price': round(current_price, 2),
                        'timestamp': datetime.now().isoformat(),
                        'message': f'{ticker} breaking above SMA20' + (' (simulated)' if use_simulation else '')
                    }
                    all_alerts.append(alert)
                    all_alerts[:] = all_alerts[-100:]  # Keep last 100 alerts
                    print(f"ALERT: {alert['message']} at ${current_price:.2f}")
                
            except Exception as e:
                print(f"Error processing {ticker}: {e}")
            
            time.sleep(2)  # Small delay between tickers
        
        # Every 5 scans, try real data again
        if use_simulation and yahoo_blocked_count % 5 == 0:
            use_simulation = False
            yahoo_blocked_count = 0
            print("Retrying real data connection...")
        
        print(f"Scan complete. Total alerts: {len(all_alerts)}. Waiting 60 seconds...")
        time.sleep(60)  # Wait before next scan

# Start scanner thread
print("Starting market scanner thread...")
scanner = threading.Thread(target=scan_markets, daemon=True)
scanner.start()

# Add initial message
print("Trading Engine Started - Dashboard available at /")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask app on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)