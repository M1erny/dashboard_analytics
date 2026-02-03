import json
import os
import yfinance as yf
import pandas as pd
from datetime import datetime

DB_FILE = "portfolio_db.json"
BASE_CURRENCY = "USD"

class PortfolioTracker:
    def __init__(self):
        self.db_file = os.path.join(os.path.dirname(__file__), DB_FILE)
        self.data = self._load_data()

    def _load_data(self):
        if not os.path.exists(self.db_file):
            return {"cash": {"amount": 0.0, "currency": "USD"}, "positions": []}
        try:
            with open(self.db_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"cash": {"amount": 0.0, "currency": "USD"}, "positions": []}

    def _save_data(self):
        with open(self.db_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def get_portfolio(self):
        return self.data

    def add_position(self, ticker, shares, price, date, currency="USD", type="Long"):
        # Check if exists, update if present? No, let's treat as unique lots for now
        # or aggregate? For simplicity V1: Aggregate if same ticker/type.
        
        # Simple Aggregation Logic
        existing = next((p for p in self.data["positions"] if p["ticker"] == ticker and p["type"] == type), None)
        
        if existing:
            # Weighted Average Price
            total_shares = existing["shares"] + shares
            # New Avg Price = ((OldShares * OldPrice) + (NewShares * NewPrice)) / TotalShares
            new_avg_price = ((existing["shares"] * existing["avg_price"]) + (shares * price)) / total_shares
            
            existing["shares"] = total_shares
            existing["avg_price"] = new_avg_price
            # Keep original date or update? Keep original for "first entry", or update to "last buy"?
            # Let's keep original for now.
        else:
            new_pos = {
                "ticker": ticker.upper(),
                "shares": shares,
                "avg_price": price,
                "date": date,
                "currency": currency.upper(),
                "type": type
            }
            self.data["positions"].append(new_pos)
            
        self._save_data()
        return self.data

    def remove_position(self, ticker):
        self.data["positions"] = [p for p in self.data["positions"] if p["ticker"] != ticker.upper()]
        self._save_data()
        return self.data

    def get_summary(self):
        # Fetch current prices for all tickers
        positions = self.data["positions"]
        if not positions:
            return {
                "total_value": self.data["cash"]["amount"],
                "positions": [],
                "cash": self.data["cash"]
            }

        tickers = list(set([p["ticker"] for p in positions]))
        # Fetch FX (if any non-USD)
        currencies = list(set([p["currency"] for p in positions if p["currency"] != "USD"]))
        fx_pairs = [f"{c}USD=X" for c in currencies] 
        
        # Download Data
        data = yf.download(tickers + fx_pairs, period="1d", progress=False)
        
        # Process Summary
        summary_positions = []
        total_value_usd = self.data["cash"]["amount"] # Start with cash (assuming USD cash for now)
        
        # Normalize Data Access (MultiIndex check)
        # yfinance structure varies by version/ticker count
        def get_close(ticker, df):
            try:
                # If Multi-Level Columns (Price, Ticker)
                if isinstance(df.columns, pd.MultiIndex):
                     # Try getting 'Close' first
                     if 'Close' in df.columns.get_level_values(0):
                         # If ticker in level 1
                         if ticker in df.columns.get_level_values(1):
                             val = df['Close'][ticker].iloc[-1]
                         else:
                             return None
                     else:
                         return None
                else:
                    # Single level
                     if ticker in df.columns:
                        return df[ticker].iloc[-1]
                     elif 'Close' in df.columns:
                        return df['Close'].iloc[-1]
                     return None
                return val
            except:
                return None

        for p in positions:
            ticker = p["ticker"]
            current_price = get_close(ticker, data)
            current_fx = 1.0
            
            if p["currency"] != "USD":
                fx_ticker = f"{p['currency']}USD=X"
                fx_rate = get_close(fx_ticker, data)
                if fx_rate: current_fx = fx_rate
            
            if current_price:
                # Value calculation
                market_value = p["shares"] * current_price
                market_value_usd = market_value * current_fx
                
                cost_basis = p["shares"] * p["avg_price"]
                unrealized_pl = (current_price - p["avg_price"]) * p["shares"]
                unrealized_pl_pct = (unrealized_pl / cost_basis) if cost_basis else 0
                
                # Directions: Short logic checks
                if p["type"] == "Short":
                     # P&L is reversed: (Entry - Current) * Shares
                     unrealized_pl = (p["avg_price"] - current_price) * p["shares"]
                     unrealized_pl_pct = (unrealized_pl / cost_basis) if cost_basis else 0
                     # Market Value for Short is technically a liability, but for "Exposure" we treat as positive magnitude?
                     # Let's report Net Liquidation Value contribution:
                     # For Short: You hold Cash from sale. Liability is current cost to buy back.
                     # This gets complex. Simplification -> Total Portfolio Equity = Cash + Long Value - Short Liability
                     pass

                summary_positions.append({
                    **p,
                    "current_price": float(current_price),
                    "market_value_usd": float(market_value_usd),
                    "unrealized_pl_usd": float(unrealized_pl * current_fx),
                    "return_pct": float(unrealized_pl_pct)
                })
                
                if p["type"] == "Long":
                    total_value_usd += market_value_usd
                else:
                    # For Short, we assume cash was received at open (so cash balance is higher).
                    # We subtract current buy-back cost.
                    total_value_usd -= market_value_usd 

            else:
                # Price not found
                summary_positions.append({
                    **p,
                    "error": "Price unavailable"
                })

        return {
            "total_equity_usd": total_value_usd,
            "cash": self.data["cash"],
            "positions": summary_positions
        }
