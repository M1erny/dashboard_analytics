export interface PeriodInfo {
    Start_Date: string;
    End_Date: string;
    Years: number;
}

export interface TalebMetrics {
    Kurtosis: number;
    Skewness: number;
    Fat_Tail_Rating: string;
}

export interface Vitals {
    beta: number;
    longOnlyBeta?: number;
    shortOnlyBeta?: number;
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
    ytdAlphaRaw: number;
    ytdMaxDrawdown: number;
    benchmarkYtdMaxDrawdown: number;
    ytdReturnGross: number;
    ytdFinancingCost: number;
    annualFinancingCost: number;
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
    linearImpact?: number;
    marketMove?: number;
}

export interface ConvexityMetrics {
    upsideCapture: number;
    downsideCapture: number;
    captureSpread: number;
    quadraticCoeffs: [number, number, number]; // [β₂, β₁, α]
    rSquared: number;
    isConvex: boolean;
    scatterData: [number, number][]; // [benchRet, portRet][]
}

export interface PeriodicReturn {
    ticker: string;
    sector?: string;
    r1d: number | null;  // 1 Day return
    r7d: number | null;  // 7 Day return
    r1m: number | null;  // 1 Month return
    r1y: number | null;
    ytd: number;
    ytdContribution: number | null;  // weight * return * direction
    r1dContribution: number | null;
    r7dContribution: number | null;
    weight: number | null;
    currentWeight: number | null;
    direction: 'Long' | 'Short' | null;
    lastPrice: number | null;  // Last fetched price (original currency)
    currency: string;  // Original currency (USD, EUR, etc.)
    volatility: number | null;  // Annualized volatility (std dev)
    volumeIndicator: number | null;  // 7d avg volume / YTD avg volume
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

export interface CountryAllocation {
    long: number;
    short: number;
    contribution: number;
    tickers: { ticker: string; weight: number; type: string; contribution: number }[];
}

export interface FullRiskReport {
    vitals: Vitals;
    leverage: LeverageStats;
    activeRisks: RiskAttribution[];
    stressTests: StressTest[];
    periodicReturns: PeriodicReturn[];
    history: HistoryPoint[];
    ytdHistory?: HistoryPoint[];
    volumeWeightedCorrelation?: CorrelationMatrix;
    talebMetrics?: TalebMetrics;
    countryAllocation?: Record<string, CountryAllocation>;
    convexity?: ConvexityMetrics | null;
    error?: string;
}

export type CostTier = 'institutional' | 'retail' | 'none';

export const fetchDashboardData = async (retries = 5, delay = 3000, force = false, costTier: CostTier = 'retail'): Promise<FullRiskReport | null> => {
    for (let i = 0; i < retries; i++) {
        try {
            // Use relative path - Vite proxy will handle forwarding to backend
            const url = force
                ? `/api/metrics?force=true&costTier=${costTier}&t=${new Date().getTime()}`
                : `/api/metrics?costTier=${costTier}`;

            // Add 90 second timeout for slow backend (insider data fetching)
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 90000);

            const response = await fetch(url, { signal: controller.signal });
            clearTimeout(timeoutId);

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
                    ytdHistory: data.ytdHistory || [],
                    volumeWeightedCorrelation: data.volumeWeightedCorrelation || undefined,
                    talebMetrics: data.talebMetrics,
                    countryAllocation: data.countryAllocation,
                    convexity: data.convexity || null,
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
