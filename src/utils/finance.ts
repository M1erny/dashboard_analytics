export interface PeriodInfo {
    Start_Date: string;
    End_Date: string;
    Years: number;
}

export interface Vitals {
    beta: number;
    annualReturn: number;
    annualVol: number;
    sharpe: number;
    sortino: number;
    maxDrawdown: number;
    rolling1mVol: number;
    rolling1mVolBenchmark: number;
    cvar95: number;
    ytdReturn: number;
    benchmarkYtd: number;
    benchmarkVol: number;
    ytdBeta: number;
    // Standardized Sharpe Metrics
    ytdSharpe: number;
    benchmarkYtdSharpe: number;
    benchmarkHistSharpe: number;
    ytdReturnPln: number;
    wigYtd: number;
    msciYtd: number;
    ytdLongsContrib: number;
    ytdShortsContrib: number;
    jensensAlpha: number;
    ytdAlpha: number;
    ytdMaxDrawdown: number;
    benchmarkYtdMaxDrawdown: number;
    currencyExposure: Record<string, number>;
    fxWatchlist: Record<string, number>;
    periodInfo: PeriodInfo;
}

export interface LeverageStats {
    Long_Exp: number;
    Short_Exp: number;
    Gross_Exp: number;
    Net_Exp: number;
    Daily_Drag: number;
}

export interface RiskAttribution {
    ticker: string;
    weight: number;
    pctRisk: number;
    mctr: number;
}

export interface StressTest {
    scenario: string;
    impact: number;
}

export interface PeriodicReturn {
    ticker: string;
    r1m: number | null;  // 1 Month return
    r1y: number | null;
    r5y: number | null;
    ytd: number;
    ytdContribution: number | null;  // weight * return * direction
    weight: number | null;
    direction: 'Long' | 'Short' | null;
}

export interface MonteCarloPoint {
    day: number;
    p05: number;
    p50: number;
    p95: number;
}

export interface HistoryPoint {
    date: string;
    portfolio: number;
    benchmark: number;
    drawdown: number;
}

export interface CorrelationMatrix {
    tickers: string[];
    matrix: (number | null)[][];
}

export interface FullRiskReport {
    vitals: Vitals;
    leverage: LeverageStats;
    activeRisks: RiskAttribution[];
    stressTests: StressTest[];
    periodicReturns: PeriodicReturn[];
    monteCarlo: MonteCarloPoint[];
    history: HistoryPoint[];
    ytdHistory?: HistoryPoint[];
    volumeWeightedCorrelation?: CorrelationMatrix;
    error?: string;
}

export const fetchDashboardData = async (retries = 5, delay = 1000, force = false): Promise<FullRiskReport | null> => {
    for (let i = 0; i < retries; i++) {
        try {
            // Use relative path - Vite proxy will handle forwarding to backend
            const url = force
                ? `/api/metrics?t=${new Date().getTime()}`
                : `/api/metrics`;

            const response = await fetch(url);
            if (!response.ok) {
                // If 500 or 404, might be temporary, but usually logic error.
                // However, if proxy refuses connection, it might appear as bad gateway or similar depending on vite.
                const text = await response.text();
                console.warn(`Attempt ${i + 1}/${retries} failed: ${text}`);
            } else {
                const data = await response.json();

                // The server now returns data already formatted for the frontend (mostly).
                // We just need to map properties to the FullRiskReport interface.

                // Safety check: ensure vitals exists
                if (!data.vitals) {
                    throw new Error("Invalid response format: 'vitals' missing");
                }

                return {
                    vitals: {
                        ...data.vitals,
                        // Ensure defaults for critical nested objects if missing from partial server response
                        currencyExposure: data.vitals.currencyExposure || {},
                        fxWatchlist: data.vitals.fxWatchlist || {},
                        periodInfo: data.vitals.periodInfo || { Start_Date: "N/A", End_Date: "N/A", Years: 0 }
                    },
                    leverage: data.leverage || { Long_Exp: 0, Short_Exp: 0, Gross_Exp: 0, Net_Exp: 0, Daily_Drag: 0 },
                    history: data.history || [],
                    periodicReturns: data.periodicReturns || [],
                    activeRisks: data.riskAttribution || [], // Rename data.riskAttribution -> activeRisks
                    stressTests: data.stressTests || [],
                    monteCarlo: data.monteCarlo || [],
                    ytdHistory: data.ytdHistory || [],
                    volumeWeightedCorrelation: data.volumeWeightedCorrelation || undefined,
                    error: data.error
                };
            }
        } catch (error) {
            console.warn(`Attempt ${i + 1}/${retries} failed to connect:`, error);
        }

        // Wait before next retry
        if (i < retries - 1) await new Promise(res => setTimeout(res, delay));
    }

    console.error("Failed to fetch dashboard data after multiple attempts.");
    return null;
};
