"""
Fixed Version - Trading Engine with Integrated Dashboard
Works with Yahoo Finance (No API Key Required)
"""

import asyncio
import json
import yaml
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import yfinance as yf
import threading
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# HTML Dashboard Template
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Engine Dashboard</title>
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
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        h1 {
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.2);
            transition: transform 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
        }
        
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }
        
        .stat-label {
            opacity: 0.9;
            font-size: 0.9em;
        }
        
        .alerts-container {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .alerts-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .clear-btn {
            background: rgba(255, 255, 255, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.3);
            color: white;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.3s ease;
        }
        
        .clear-btn:hover {
            background: rgba(255, 255, 255, 0.3);
        }
        
        .alert-item {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 15px;
            display: grid;
            grid-template-columns: auto 1fr auto auto;
            gap: 20px;
            align-items: center;
            animation: slideIn 0.3s ease-out;
            border-left: 4px solid #4caf50;
        }
        
        .alert-item.volume-spike {
            border-left-color: #ff9800;
        }
        
        .alert-item.new {
            background: rgba(76, 175, 80, 0.2);
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
            font-size: 1.3em;
            background: rgba(255, 255, 255, 0.2);
            padding: 8px 12px;
            border-radius: 8px;
            min-width: 80px;
            text-align: center;
        }
        
        .alert-message {
            font-size: 0.95em;
            opacity: 0.9;
        }
        
        .alert-type {
            background: rgba(255, 255, 255, 0.2);
            padding: 5px 10px;
            border-radius: 20px;
            font-size: 0.8em;
            text-transform: uppercase;
            font-weight: 600;
        }
        
        .alert-type.BREAKOUT {
            background: rgba(76, 175, 80, 0.3);
        }
        
        .alert-type.VOLUME_SPIKE {
            background: rgba(255, 152, 0, 0.3);
        }
        
        .alert-price {
            font-family: 'Courier New', monospace;
            font-size: 1.1em;
            font-weight: bold;
        }
        
        .alert-time {
            font-size: 0.85em;
            opacity: 0.7;
        }
        
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #4caf50;
            margin-left: 10px;
            animation: pulse 2s infinite;
        }
        
        .status-indicator.offline {
            background: #f44336;
            animation: none;
        }
        
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(76, 175, 80, 0); }
            100% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0); }
        }
        
        .no-alerts {
            text-align: center;
            padding: 60px 20px;
            opacity: 0.7;
        }
        
        .no-alerts svg {
            width: 80px;
            height: 80px;
            margin-bottom: 20px;
            opacity: 0.5;
        }
        
        .ticker-list {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 20px;
        }
        
        .ticker-badge {
            background: rgba(255, 255, 255, 0.1);
            padding: 5px 10px;
            border-radius: 15px;
            font-size: 0.85em;
        }
        
        .refresh-indicator {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(0, 0, 0, 0.5);
            padding: 10px 20px;
            border-radius: 25px;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Trading Engine Dashboard <span id="status" class="status-indicator"></span></h1>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">📊 Total Alerts</div>
                <div class="stat-value" id="total-alerts">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">🔍 Active Tickers</div>
                <div class="stat-value" id="active-tickers">10</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">⏰ Last Update</div>
                <div class="stat-value" id="last-update">--:--</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">📈 Data Source</div>
                <div class="stat-value">Yahoo Finance</div>
            </div>
        </div>
        
        <div class="alerts-container">
            <div class="alerts-header">
                <h2>🔔 Recent Alerts</h2>
                <button class="clear-btn" onclick="clearOldAlerts()">Clear Old</button>
            </div>
            <div id="alerts-list">
                <div class="no-alerts">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <p style="font-size: 1.2em; margin-bottom: 10px;">Waiting for market signals...</p>
                    <p style="font-size: 0.9em;">The system scans every 60 seconds</p>
                    <div class="ticker-list">
                        <span class="ticker-badge">AAPL</span>
                        <span class="ticker-badge">MSFT</span>
                        <span class="ticker-badge">GOOGL</span>
                        <span class="ticker-badge">TSLA</span>
                        <span class="ticker-badge">NVDA</span>
                        <span class="ticker-badge">META</span>
                        <span class="ticker-badge">AMZN</span>
                        <span class="ticker-badge">AMD</span>
                        <span class="ticker-badge">SPY</span>
                        <span class="ticker-badge">QQQ</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="refresh-indicator" id="refresh-indicator">
        Refreshing in <span id="countdown">5</span>s
    </div>
    
    <script>
        let totalAlerts = 0;
        let lastAlertTime = null;
        let countdown = 5;
        let isConnected = false;
        
        function formatTime(timestamp) {
            const date = new Date(timestamp);
            const now = new Date();
            const diff = now - date;
            
            if (diff < 60000) return 'Just now';
            if (diff < 3600000) return Math.floor(diff / 60000) + ' min ago';
            if (diff < 86400000) return Math.floor(diff / 3600000) + ' hours ago';
            return date.toLocaleDateString();
        }
        
        async function fetchAlerts() {
            try {
                const response = await fetch('/api/alerts');
                const alerts = await response.json();
                
                isConnected = true;
                document.getElementById('status').classList.remove('offline');
                
                totalAlerts = alerts.length;
                document.getElementById('total-alerts').textContent = totalAlerts;
                
                const alertsList = document.getElementById('alerts-list');
                
                if (alerts.length === 0) {
                    alertsList.innerHTML = `
                        <div class="no-alerts">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            <p style="font-size: 1.2em; margin-bottom: 10px;">Waiting for market signals...</p>
                            <p style="font-size: 0.9em;">The system scans every 60 seconds</p>
                            <div class="ticker-list">
                                <span class="ticker-badge">AAPL</span>
                                <span class="ticker-badge">MSFT</span>
                                <span class="ticker-badge">GOOGL</span>
                                <span class="ticker-badge">TSLA</span>
                                <span class="ticker-badge">NVDA</span>
                                <span class="ticker-badge">META</span>
                                <span class="ticker-badge">AMZN</span>
                                <span class="ticker-badge">AMD</span>
                                <span class="ticker-badge">SPY</span>
                                <span class="ticker-badge">QQQ</span>
                            </div>
                        </div>
                    `;
                } else {
                    // Check for new alerts
                    const latestAlert = alerts[alerts.length - 1];
                    const isNew = !lastAlertTime || new Date(latestAlert.timestamp) > new Date(lastAlertTime);
                    if (isNew) {
                        lastAlertTime = latestAlert.timestamp;
                    }
                    
                    alertsList.innerHTML = alerts.slice(-20).reverse().map((alert, index) => {
                        const alertClass = alert.type === 'VOLUME_SPIKE' ? 'volume-spike' : '';
                        const newClass = index === 0 && isNew ? 'new' : '';
                        
                        return `
                            <div class="alert-item ${alertClass} ${newClass}">
                                <div class="alert-ticker">${alert.ticker}</div>
                                <div class="alert-message">${alert.message}</div>
                                <div style="text-align: right;">
                                    <span class="alert-type ${alert.type}">${alert.type.replace('_', ' ')}</span>
                                    <div class="alert-price">$${alert.price.toFixed(2)}</div>
                                </div>
                                <div class="alert-time">${formatTime(alert.timestamp)}</div>
                            </div>
                        `;
                    }).join('');
                }
                
                // Update last update time
                document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
                
            } catch (error) {
                console.error('Error fetching alerts:', error);
                isConnected = false;
                document.getElementById('status').classList.add('offline');
            }
            
            // Reset countdown
            countdown = 5;
        }
        
        function clearOldAlerts() {
            if (confirm('Clear all alerts older than 1 hour?')) {
                // In a real implementation, this would call an API endpoint
                console.log('Clearing old alerts...');
            }
        }
        
        // Update countdown
        setInterval(() => {
            countdown--;
            if (countdown <= 0) {
                countdown = 5;
                fetchAlerts();
            }
            document.getElementById('countdown').textContent = countdown;
        }, 1000);
        
        // Initial fetch
        fetchAlerts();
    </script>
</body>
</html>
'''

class YahooDataConnector:
    """Free data connector using yfinance"""
    
    def __init__(self):
        self.cache = {}
        self.cache_duration = 60  # Cache for 60 seconds
    
    def get_realtime_data(self, ticker):
        """Get near real-time data from Yahoo Finance"""
        try:
            stock = yf.Ticker(ticker)
            
            # Get current info
            info = stock.info
            
            # Get latest price
            data = stock.history(period="1d", interval="1m")
            
            if not data.empty:
                latest = data.iloc[-1]
                return {
                    'ticker': ticker,
                    'price': latest['Close'],
                    'volume': latest['Volume'],
                    'high': latest['High'],
                    'low': latest['Low'],
                    'open': latest['Open'],
                    'timestamp': data.index[-1]
                }
        except Exception as e:
            logger.error(f"Error fetching {ticker}: {e}")
        return None
    
    def get_historical_data(self, ticker, period="5d", interval="5m"):
        """Get historical data for indicators"""
        try:
            stock = yf.Ticker(ticker)
            return stock.history(period=period, interval=interval)
        except Exception as e:
            logger.error(f"Error fetching historical data for {ticker}: {e}")
            return pd.DataFrame()

class SimpleRuleEngine:
    """Simplified rule engine for testing"""
    
    def __init__(self):
        self.alerts = []
        
    def check_rules(self, ticker, current_data, historical_data):
        """Check trading rules"""
        alerts = []
        
        if historical_data.empty:
            return alerts
        
        # Calculate simple indicators
        historical_data['SMA_20'] = historical_data['Close'].rolling(window=20).mean()
        historical_data['Volume_Avg'] = historical_data['Volume'].rolling(window=20).mean()
        
        current_price = current_data['price']
        current_volume = current_data['volume']
        
        # Rule 1: Price above SMA20 with high volume
        if len(historical_data) >= 20:
            sma_20 = historical_data['SMA_20'].iloc[-1]
            avg_volume = historical_data['Volume_Avg'].iloc[-1]
            
            if current_price > sma_20 and current_volume > avg_volume * 1.5:
                alerts.append({
                    'ticker': ticker,
                    'type': 'BREAKOUT',
                    'price': current_price,
                    'message': f'{ticker} breaking above SMA20 with high volume',
                    'timestamp': datetime.now().isoformat()
                })
        
        # Rule 2: Volume spike
        if len(historical_data) >= 5:
            avg_volume_5 = historical_data['Volume'].tail(5).mean()
            if current_volume > avg_volume_5 * 3:
                alerts.append({
                    'ticker': ticker,
                    'type': 'VOLUME_SPIKE',
                    'price': current_price,
                    'message': f'{ticker} unusual volume spike detected (3x average)',
                    'timestamp': datetime.now().isoformat()
                })
        
        return alerts

# Flask app for dashboard
app = Flask(__name__)
CORS(app)

connector = YahooDataConnector()
rule_engine = SimpleRuleEngine()
all_alerts = []

@app.route('/')
def dashboard():
    """Serve the dashboard HTML"""
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/alerts')
def get_alerts():
    """Get recent alerts"""
    return jsonify(all_alerts[-50:])  # Last 50 alerts

@app.route('/api/market/<ticker>')
def get_market_data(ticker):
    """Get current market data"""
    data = connector.get_realtime_data(ticker)
    if data:
        return jsonify(data)
    return jsonify({'error': 'Data not found'}), 404

@app.route('/api/status')
def get_status():
    """Get system status"""
    return jsonify({
        'status': 'running',
        'alerts_count': len(all_alerts),
        'timestamp': datetime.now().isoformat()
    })

def scan_markets():
    """Background scanner"""
    # Test watchlist
    watchlist = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'META', 'AMZN', 'AMD', 'SPY', 'QQQ']
    
    while True:
        logger.info("Starting market scan...")
        for ticker in watchlist:
            try:
                # Get current data
                current = connector.get_realtime_data(ticker)
                if not current:
                    continue
                
                # Get historical data
                historical = connector.get_historical_data(ticker, period="1d", interval="5m")
                
                # Check rules
                alerts = rule_engine.check_rules(ticker, current, historical)
                
                # Store alerts
                for alert in alerts:
                    all_alerts.append(alert)
                    logger.info(f"Alert: {alert['message']}")
                
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")
            
            time.sleep(1)  # Small delay between tickers to avoid rate limiting
        
        logger.info(f"Scan complete. Total alerts: {len(all_alerts)}. Waiting 60 seconds...")
        time.sleep(60)  # Wait 1 minute before next scan

if __name__ == "__main__":
    # Start scanner in background
    scanner_thread = threading.Thread(target=scan_markets, daemon=True)
    scanner_thread.start()
    
    # Start Flask app
    print("\n" + "="*60)
    print("🚀 TRADING ENGINE STARTED SUCCESSFULLY!")
    print("="*60)
    print("📊 Dashboard: http://localhost:5000")
    print("📡 API Endpoints:")
    print("   - Alerts: http://localhost:5000/api/alerts")
    print("   - Status: http://localhost:5000/api/status")
    print("   - Market: http://localhost:5000/api/market/AAPL")
    print("="*60)
    print("📌 No API key required - Using Yahoo Finance")
    print("⏱️  Scanning 10 stocks every 60 seconds")
    print("🔍 Watching: AAPL, MSFT, GOOGL, TSLA, NVDA, META, AMZN, AMD, SPY, QQQ")
    print("="*60)
    print("Press CTRL+C to stop\n")
    
    app.run(debug=False, port=5000, host='0.0.0.0')