"""
Fixed Backtest Script - Tests Simple Trading Strategy
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

def quick_backtest():
    """Quick backtest using Yahoo Finance data"""
    
    print("=" * 60)
    print("📊 SIMPLE BACKTEST - SMA CROSSOVER STRATEGY")
    print("=" * 60)
    
    # Download historical data
    ticker = "AAPL"
    print(f"\n📥 Downloading data for {ticker}...")
    
    # Use the new format to avoid the warning
    data = yf.download(ticker, start="2024-01-01", end="2024-12-31", auto_adjust=True, progress=True)
    
    if data.empty:
        print("❌ No data retrieved. Check your internet connection.")
        return None
    
    print(f"✅ Downloaded {len(data)} days of data")
    
    # Calculate indicators
    print("\n📈 Calculating indicators...")
    data['SMA20'] = data['Close'].rolling(window=20).mean()
    data['SMA50'] = data['Close'].rolling(window=50).mean()
    
    # Create signals (fixing the alignment issue)
    data['Signal'] = 0
    data['Position'] = 0
    
    # Generate signals when SMA20 > SMA50 (Golden Cross)
    short_window = 20
    long_window = 50
    
    # Wait for enough data
    for i in range(long_window, len(data)):
        if data['SMA20'].iloc[i] > data['SMA50'].iloc[i]:
            data.loc[data.index[i], 'Signal'] = 1
        else:
            data.loc[data.index[i], 'Signal'] = -1
    
    # Calculate positions (1 for long, 0 for no position)
    data['Position'] = data['Signal'].shift(1)
    data['Position'] = data['Position'].fillna(0)
    data['Position'] = data['Position'].replace(-1, 0)  # No short positions
    
    # Calculate returns
    data['Daily_Return'] = data['Close'].pct_change()
    data['Strategy_Return'] = data['Position'] * data['Daily_Return']
    
    # Calculate cumulative returns
    data['Cumulative_Market_Return'] = (1 + data['Daily_Return']).cumprod()
    data['Cumulative_Strategy_Return'] = (1 + data['Strategy_Return']).cumprod()
    
    # Calculate performance metrics
    print("\n📊 Calculating performance metrics...")
    
    # Remove NaN values for calculations
    valid_returns = data['Strategy_Return'].dropna()
    
    if len(valid_returns) > 0:
        # Total returns
        total_return = data['Cumulative_Strategy_Return'].iloc[-1] - 1
        market_return = data['Cumulative_Market_Return'].iloc[-1] - 1
        
        # Calculate Sharpe Ratio (assuming 0% risk-free rate)
        if valid_returns.std() != 0:
            sharpe_ratio = np.sqrt(252) * valid_returns.mean() / valid_returns.std()
        else:
            sharpe_ratio = 0
        
        # Calculate Maximum Drawdown
        cumulative = data['Cumulative_Strategy_Return'].dropna()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = drawdown.min()
        
        # Count trades
        trades = data['Signal'].diff().fillna(0)
        num_trades = len(trades[trades != 0])
        
        # Win rate
        winning_trades = valid_returns[valid_returns > 0]
        losing_trades = valid_returns[valid_returns < 0]
        if len(winning_trades) + len(losing_trades) > 0:
            win_rate = len(winning_trades) / (len(winning_trades) + len(losing_trades))
        else:
            win_rate = 0
        
        # Print results
        print("\n" + "=" * 60)
        print("📈 BACKTEST RESULTS")
        print("=" * 60)
        print(f"\n🎯 Strategy: SMA {short_window}/{long_window} Crossover")
        print(f"📅 Period: 2024-01-01 to 2024-12-31")
        print(f"🔤 Ticker: {ticker}")
        
        print(f"\n💰 RETURNS:")
        print(f"   Strategy Return: {total_return:.2%}")
        print(f"   Buy & Hold Return: {market_return:.2%}")
        print(f"   Outperformance: {(total_return - market_return):.2%}")
        
        print(f"\n📊 RISK METRICS:")
        print(f"   Sharpe Ratio: {sharpe_ratio:.2f}")
        print(f"   Max Drawdown: {max_drawdown:.2%}")
        
        print(f"\n📈 TRADING STATISTICS:")
        print(f"   Total Trades: {num_trades}")
        print(f"   Win Rate: {win_rate:.2%}")
        print(f"   Days in Position: {data['Position'].sum()}/{len(data)} ({data['Position'].mean():.1%})")
        
        # Create visualization
        print("\n📊 Generating charts...")
        create_backtest_charts(data, ticker, total_return, market_return)
        
        return {
            'data': data,
            'total_return': total_return,
            'market_return': market_return,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'num_trades': num_trades,
            'win_rate': win_rate
        }
    else:
        print("❌ Not enough data for backtest")
        return None

def create_backtest_charts(data, ticker, strategy_return, market_return):
    """Create visualization charts for backtest results"""
    
    # Set style
    plt.style.use('seaborn-v0_8-darkgrid')
    
    # Create figure with subplots
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    fig.suptitle(f'Backtest Results: {ticker} SMA Crossover Strategy', fontsize=16, fontweight='bold')
    
    # 1. Price and SMA Chart
    ax1 = axes[0]
    ax1.plot(data.index, data['Close'], label='Close Price', color='black', linewidth=1)
    ax1.plot(data.index, data['SMA20'], label='SMA 20', color='blue', alpha=0.7)
    ax1.plot(data.index, data['SMA50'], label='SMA 50', color='red', alpha=0.7)
    
    # Mark buy signals
    buy_signals = data[data['Signal'] == 1]
    if not buy_signals.empty:
        ax1.scatter(buy_signals.index, buy_signals['Close'], 
                   color='green', marker='^', s=100, label='Buy Signal', zorder=5)
    
    # Mark sell signals
    sell_signals = data[data['Signal'] == -1]
    if not sell_signals.empty:
        ax1.scatter(sell_signals.index, sell_signals['Close'], 
                   color='red', marker='v', s=100, label='Sell Signal', zorder=5)
    
    ax1.set_title('Price Action with Trading Signals')
    ax1.set_ylabel('Price ($)')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)
    
    # 2. Cumulative Returns Comparison
    ax2 = axes[1]
    ax2.plot(data.index, (data['Cumulative_Strategy_Return'] - 1) * 100, 
             label=f'Strategy ({strategy_return:.1%})', color='green', linewidth=2)
    ax2.plot(data.index, (data['Cumulative_Market_Return'] - 1) * 100, 
             label=f'Buy & Hold ({market_return:.1%})', color='blue', linewidth=2)
    ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    ax2.fill_between(data.index, (data['Cumulative_Strategy_Return'] - 1) * 100, 
                     alpha=0.3, color='green')
    ax2.set_title('Cumulative Returns Comparison')
    ax2.set_ylabel('Return (%)')
    ax2.legend(loc='best')
    ax2.grid(True, alpha=0.3)
    
    # 3. Drawdown Chart
    ax3 = axes[2]
    cumulative = data['Cumulative_Strategy_Return'].dropna()
    running_max = cumulative.expanding().max()
    drawdown = ((cumulative - running_max) / running_max) * 100
    
    # Align the indices properly
    drawdown_index = drawdown.index
    ax3.fill_between(drawdown_index, drawdown, color='red', alpha=0.5)
    ax3.plot(drawdown_index, drawdown, color='red', linewidth=1)
    ax3.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    ax3.set_title('Strategy Drawdown')
    ax3.set_ylabel('Drawdown (%)')
    ax3.set_xlabel('Date')
    ax3.grid(True, alpha=0.3)
    
    # Adjust layout and save
    plt.tight_layout()
    
    # Save the figure
    filename = f'backtest_{ticker}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    plt.savefig(filename, dpi=100, bbox_inches='tight')
    print(f"✅ Chart saved as '{filename}'")
    
    # Show the plot
    plt.show()

def run_multiple_backtests():
    """Run backtests on multiple tickers"""
    
    tickers = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA']
    results = {}
    
    print("\n" + "=" * 60)
    print("🔄 RUNNING MULTIPLE BACKTESTS")
    print("=" * 60)
    
    for ticker in tickers:
        print(f"\nTesting {ticker}...")
        try:
            # Download data
            data = yf.download(ticker, start="2024-01-01", end="2024-12-31", 
                              auto_adjust=True, progress=False)
            
            if data.empty:
                print(f"  ❌ No data for {ticker}")
                continue
            
            # Simple SMA strategy
            data['SMA20'] = data['Close'].rolling(window=20).mean()
            data['SMA50'] = data['Close'].rolling(window=50).mean()
            data['Signal'] = 0
            
            # Generate signals
            data.loc[data['SMA20'] > data['SMA50'], 'Signal'] = 1
            data['Position'] = data['Signal'].shift(1).fillna(0)
            
            # Calculate returns
            data['Returns'] = data['Close'].pct_change()
            data['Strategy_Returns'] = data['Position'] * data['Returns']
            
            # Calculate performance
            total_return = (data['Strategy_Returns'] + 1).cumprod().iloc[-1] - 1
            market_return = (data['Returns'] + 1).cumprod().iloc[-1] - 1
            
            results[ticker] = {
                'strategy_return': total_return,
                'market_return': market_return,
                'outperformance': total_return - market_return
            }
            
            print(f"  ✅ Strategy: {total_return:.2%}, Buy&Hold: {market_return:.2%}")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    # Print summary
    if results:
        print("\n" + "=" * 60)
        print("📊 SUMMARY OF ALL BACKTESTS")
        print("=" * 60)
        
        best_performer = max(results.items(), key=lambda x: x[1]['strategy_return'])
        worst_performer = min(results.items(), key=lambda x: x[1]['strategy_return'])
        
        print(f"\n🏆 Best Performer: {best_performer[0]} ({best_performer[1]['strategy_return']:.2%})")
        print(f"😞 Worst Performer: {worst_performer[0]} ({worst_performer[1]['strategy_return']:.2%})")
        
        avg_return = np.mean([r['strategy_return'] for r in results.values()])
        print(f"📊 Average Strategy Return: {avg_return:.2%}")

if __name__ == "__main__":
    print("\n🚀 Starting Backtest...\n")
    
    # Run single backtest
    results = quick_backtest()
    
    if results:
        print("\n" + "=" * 60)
        print("✅ BACKTEST COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        
        # Optionally run multiple backtests
        print("\nDo you want to test multiple tickers? (Uncomment the line below)")
        # run_multiple_backtests()
    else:
        print("\n❌ Backtest failed. Please check your internet connection and try again.")