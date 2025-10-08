# app.py - Production version for Render
import os
from flask import Flask, render_template_string, jsonify
from flask_cors import CORS
import yfinance as yf
import threading
import time
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Store alerts globally
all_alerts = []

# Mobile-optimized HTML Dashboard
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Trading Engine - Live Alerts</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
            padding: 15px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        
        h1 {
            text-align: center;
            margin-bottom: 20px;
            font-size: 1.8em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .status {
            text-align: center;
            margin-bottom: 20px;
            padding: 10px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }
        
        .status.live {
            background: rgba(76, 175, 80, 0.2);
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        
        .stat-card {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 12px;
            padding: 15px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .stat-value {
            font-size: 1.8em;
            font-weight: bold;
            margin: 8px 0;
        }
        
        .stat-label {
            opacity: 0.9;
            font-size: 0.85em;
        }
        
        .alerts-container {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .alert-item {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            animation: slideIn 0.3s ease-out;
            border-left: 3px solid #4caf50;
        }
        
        @keyframes slideIn {
            from {
                transform: translateX(-100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        
        .alert-ticker {
            font-weight: bold;
            font-size: 1.2em;
        }
        
        .alert-price {
            font-family: monospace;
            font-size: 1.1em;
            color: #4caf50;
        }
        
        .alert-time {
            font-size: 0.8em;
            opacity: 0.7;
        }
        
        .no-alerts {
            text-align: center;
            padding: 40px;
            opacity: 0.7;
        }
        
        .loading {
            text-align: center;
            padding: 20px;
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
        
        /* Mobile optimizations */
        @media (max-width: 600px) {
            h1 { font-size: 1.5em; }
            .stats { grid-template-columns: 1fr 1fr; }
            .alert-item { 
                flex-direction: column; 
                align-items: flex-start;
                gap: 8px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 Trading Engine Live</h1>
        
        <div class="status live" id="status">
            🟢 LIVE - Scanning Markets
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">Total Alerts</div>
                <div class="stat-value" id="total-alerts">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Active Tickers</div>
                <div class="stat-value">10</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Last Update</div>
                <div class="stat-value" id="last-update">--:--</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Data Source</div>
                <div class="stat-value">Yahoo</div>
            </div>
        </div>
        
        <div class="alerts-container">
            <h2 style="margin-bottom: 15px;">🔔 Recent Alerts</h2>
            <div id="alerts-list">
                <div class="loading">
                    <div class="spinner"></div>
                    <p style="margin-top: 15px;">Waiting for market signals...</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let totalAlerts = 0;
        
        async function fetchAlerts() {
            try {
                const response = await fetch('/api/alerts');
                const alerts = await response.json();
                
                totalAlerts = alerts.length;
                document.getElementById('total-alerts').textContent = totalAlerts;
                document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
                
                const alertsList = document.getElementById('alerts-list');
                
                if (alerts.length === 0) {
                    alertsList.innerHTML = `
                        <div class="no-alerts">
                            <p>📊 No alerts yet</p>
                            <p style="font-size: 0.9em; margin-top: 10px;">System scans every 60 seconds</p>
                        </div>
                    `;
                } else {
                    alertsList.innerHTML = alerts.slice(-15).reverse().map(alert => `
                        <div class="alert-item">
                            <div>
                                <div class="alert-ticker">${alert.ticker}</div>
                                <div class="alert-time">${new Date(alert.timestamp).toLocaleTimeString()}</div>
                            </div>
                            <div class="alert-price">$${alert.price.toFixed(2)}</div>
                        </div>
                    `).join('');
                }
            } catch (error) {
                console.error('Error fetching alerts:', error);
                document.getElementById('status').textContent = '🔴 Connection Error';
                document.getElementById('status').classList.remove('live');
            }
        }
        
        // Fetch alerts every 5 seconds
        setInterval(fetchAlerts, 5000);
        fetchAlerts();
    </script>
</body>
</html>
'''

class YahooDataConnector:
    """Yahoo Finance data connector"""
    
    def get_realtime_data(self, ticker):
        try:
            stock = yf.Ticker(ticker)
            data = stock.history(period="1d", interval="1m")
            
            if not data.empty:
                latest = data.iloc[-1]
                return {
                    'ticker': ticker,
                    'price': latest['Close'],
                    'volume': latest['Volume'],
                    'timestamp': data.index[-1]
                }
        except Exception as e:
            logger.error(f"Error fetching {ticker}: {e}")
        return None
    
    def get_historical_data(self, ticker, period="5d", interval="5m"):
        try:
            stock = yf.Ticker(ticker)
            return stock.history(period=period, interval=interval)
        except Exception as e:
            logger.error(f"Error fetching historical data for {ticker}: {e}")
            return None

connector = YahooDataConnector()

@app.route('/')
def index():
    """Serve the dashboard"""
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/alerts')
def get_alerts():
    """Get recent alerts"""
    return jsonify(all_alerts[-50:])

@app.route('/api/status')
def get_status():
    """Get system status"""
    return jsonify({
        'status': 'running',
        'alerts_count': len(all_alerts),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/health')
def health():
    """Health check endpoint for Render"""
    return jsonify({'status': 'healthy'}), 200

def scan_markets():
    """Background market scanner"""
    watchlist = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'META', 'AMZN', 'AMD', 'SPY', 'QQQ']
    
    while True:
        logger.info("Starting market scan...")
        
        for ticker in watchlist:
            try:
                current = connector.get_realtime_data(ticker)
                if not current:
                    continue
                
                historical = connector.get_historical_data(ticker, period="1d", interval="5m")
                
                if historical is not None and not historical.empty:
                    # Simple alert logic
                    sma_20 = historical['Close'].rolling(window=20).mean()
                    
                    if len(historical) >= 20:
                        current_price = current['price']
                        sma_value = sma_20.iloc[-1]
                        
                        if current_price > sma_value * 1.01:  # 1% above SMA
                            alert = {
                                'ticker': ticker,
                                'price': current_price,
                                'message': f'{ticker} breaking above SMA20',
                                'timestamp': datetime.now().isoformat(),
                                'type': 'BREAKOUT'
                            }
                            all_alerts.append(alert)
                            all_alerts[:] = all_alerts[-100:]  # Keep last 100
                            logger.info(f"Alert: {alert['message']}")
                
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")
            
            time.sleep(2)  # Small delay between tickers
        
        logger.info(f"Scan complete. Total alerts: {len(all_alerts)}")
        time.sleep(60)  # Wait 60 seconds before next scan

# Start scanner thread
scanner_thread = threading.Thread(target=scan_markets, daemon=True)
scanner_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)