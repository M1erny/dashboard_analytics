# Institutional Portfolio Dashboard

## Overview
The **Institutional Portfolio Dashboard** is a high-performance risk analytics platform designed for monitoring hedge fund portfolios. It provides real-time insights into portfolio health, risk exposure, and performance attribution, utilizing institutional-grade financial models.

The application features a robust **Python/FastAPI backend** for heavy quantitative lifting (VaR, CVaR, Monte Carlo) and a sleek **React/TypeScript frontend** for data visualization.

## Key Features

### 📊 Performance & Risk Analytics
- **Standardized YTD Calculation:** Tracks performance using the previous year's closing price (Dec 31) as the base, ensuring industry-standard accuracy.
- **Advanced Risk Metrics:** Real-time calculation of **Value at Risk (VaR 95%)**, **CVaR (Expected Shortfall)**, **Sharpe Ratio**, **Sortino Ratio**, and **Beta**.
- **Dynamic Benchmarking:** Compare performance against major indices:
    - **SPY** (S&P 500)
    - **WIG20** (Warsaw Stock Exchange)
    - **URTH** (MSCI World)

### 🧪 Simulation & Stress Testing
- **Monte Carlo Simulation:** Runs 1,000 path simulations over a 60-day horizon to forecast potential portfolio trajectories.
- **Stress Testing:** Evaluates portfolio resilience under hypothetical market scenarios (e.g., Market Crash -10%, Surge +10%).

### 📉 Risk Attribution
- **Marginal Contribution to Total Risk (MCTR):** Decomposes portfolio volatility to identify which assets are the primary drivers of risk.
- **Correlation Heatmap:** Visualizes cross-asset correlations to detect diversification breakdowns.

---

## Tech Stack

### Backend (Quantitative Engine)
- **Language:** Python 3.12+
- **Framework:** FastAPI
- **Key Libraries:** `pandas`, `numpy`, `yfinance`, `scipy`

### Frontend (User Interface)
- **Framework:** React 19 + TypeScript
- **Build Tool:** Vite
- **Styling:** TailwindCSS v4
- **Visualization:** Recharts, Lucide React

---

## Installation & Setup

### Prerequisites
- **Python 3.10+**
- **Node.js 18+**

### Installation Steps

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/yourusername/portfolio-dashboard-2026.git
    cd portfolio-dashboard-2026
    ```

2.  **Install Backend Dependencies**
    ```bash
    cd backend
    pip install -r requirements.txt
    cd ..
    ```

3.  **Install Frontend Dependencies**
    ```bash
    npm install
    ```

---

## Usage

### 🚀 One-Click Launcher (Recommended)
This project comes with a **Desktop Shortcut** integration for Windows.
1.  Locate the **"Portfolio Dashboard"** shortcut on your Desktop.
2.  Double-click to launch.
3.  This script automatically:
    - Starts the FastAPI backend.
    - Starts the Vite frontend.
    - Opens your default browser to the dashboard.

### Manual Startup
If you prefer to run the services manually:

**Terminal 1 (Backend):**
```bash
cd backend
python server.py
```

**Terminal 2 (Frontend):**
```bash
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Architecture

```
portfolio-dashboard-2026/
├── backend/
│   ├── risk.py            # Core financial modeling & data engine
│   ├── server.py          # FastAPI server endpoints
│   └── debug_*.py         # Verification tools
├── src/
│   ├── components/        # React UI components (Dashboard, Charts)
│   ├── utils/             # Helper functions
│   └── App.tsx            # Main application entry
├── start_dashboard.bat    # Windows launcher script
└── README.md              # Project documentation
```

---

## License
Private / Proprietary. 
