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

/**
 * What a benchmark tile is actually showing. `label` is the series' real name,
 * `currency` the currency the return is measured in, and `warning` is set when
 * the backend had to fall back to a series it cannot describe cleanly.
 */
export interface BenchmarkSource {
    ticker: string;
    label: string;
    basis: string;
    quoteCurrency: string;
    currency: string;
    note?: string;
    warning?: string;
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
    ytdCorrelation?: number;
    // Standardized Sharpe Metrics
    ytdSharpe: number;
    benchmarkYtdSharpe: number;
    benchmarkHistSharpe: number;
    // YTD Volatility (annualized)
    ytdVol?: number;
    benchmarkYtdVol?: number;
    ytdReturnPln: number;
    wigYtd: number;
    msciYtd: number;
    wigBenchmark?: BenchmarkSource;
    msciBenchmark?: BenchmarkSource;
    ytdLongsContrib: number;
    ytdShortsContrib: number;
    jensensAlpha: number;
    ytdAlpha: number;
    ytdAlphaRaw: number;
    ytdMaxDrawdown: number;
    benchmarkYtdMaxDrawdown: number;
    ytdReturnGross: number;
    ytdSecurityGrossContribution?: number;
    ytdFinancingCost: number;
    ytdDirectFinancingCost?: number;
    annualFinancingCost: number;
    ytdCapmExpectedReturn?: number;
    performanceScope?: string;
    contributionScope?: string;
    financingScope?: string;
    currencyExposure: Record<string, number>;
    currencyExposureNet?: Record<string, number>;
    currencyExposureGross?: Record<string, number>;
    currencyExposureGrossShare?: Record<string, number>;
    fxWatchlist: Record<string, number>;
    periodInfo: PeriodInfo;
    periodLabel?: string;
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
    fittedImpact?: number;
    shapeEffect?: number;
    alphaEffect?: number;
    modelCurve?: number;
    modelSlope?: number;
    modelIntercept?: number;
    /** 'static_current_book' means the YTD beta was unusable and this estimate
     *  fell back to a replay of today's book over the full download window. */
    betaSource?: 'ytd_realised' | 'static_current_book';
    marketMove?: number;
    stressDays?: number;
    dailyMarketMove?: number;
}

export interface ScatterContributor {
    t: string;   // ticker
    c: number;   // contribution to portfolio return that day (decimal)
    r: number;   // raw stock price move that day (decimal)
}

export interface ScatterDataPoint {
    d: string;   // date
    b: number;   // benchmark (SPY) return
    p: number;   // portfolio return
    top: ScatterContributor[];  // top 3 positive contributors
    bot: ScatterContributor[];  // top 3 negative contributors
}

export interface ConvexityMetrics {
    upsideCapture: number;
    downsideCapture: number;
    captureSpread: number;
    quadraticCoeffs: [number, number, number]; // [β₂, β₁, α]
    linearCoeffs?: [number, number]; // [β, α]
    rSquared: number;
    isConvex: boolean;
    scatterData: ScatterDataPoint[];
}

export interface PeriodicReturn {
    ticker: string;
    sector?: string;
    r1d: number | null;  // 1 Day return
    // Which sessions r1d actually spans. Close is forward-filled, so the window can be
    // wider than one day when a venue has not reported its close yet.
    r1dWindowFrom?: string | null;
    r1dWindowTo?: string | null;
    // Latest session with real volume. Below r1dWindowTo means the newest price is a
    // live/patched quote rather than a settled close.
    r1dSettledThrough?: string | null;
    r7d: number | null;  // 7 Day return
    r1m: number | null;  // 1 Month return
    r1y: number | null;
    ytd: number;
    ytdContribution: number | null;  // weight * return * direction
    sinceRebalanceContribution?: number | null;  // since latest rebalance, measured on rebalance book NAV
    sinceRebalanceContributionYtdBasis?: number | null;  // same period, scaled to YTD Total's January-equity basis
    sinceRebalanceStartDate?: string | null;
    r1dContribution: number | null;
    r7dContribution: number | null;
    weight: number | null;
    currentWeight: number | null;
    direction: 'Long' | 'Short' | null;
    status?: 'Active' | 'Exited' | 'Planned';
    lastPrice: number | null;  // Last fetched price (original currency)
    entryPrice?: number | null;
    currency: string;  // Original currency (USD, EUR, etc.)
    volatility: number | null;  // Annualized volatility (std dev)
    volumeIndicator: number | null;  // 7d avg volume / YTD avg volume
}

export interface RebalanceEvent {
    date: string;
    effectiveDate: string;
    label: string;
    source: string;
    executionTiming?: string;
    longExposure: number;
    shortExposure: number;
    grossExposure: number;
    netExposure: number;
    positionCount: number;
    dailyFinancingDrag?: number;
    annualFinancingCost?: number;
    segmentFinancingCost?: number;
    segmentFinancingImpact?: number;
    cumulativeFinancingCost?: number;
    cumulativeFinancingImpact?: number;
    grossStartValue?: number;
    grossEndValue?: number;
    netStartValue?: number;
    netEndValue?: number;
}

export interface RebalanceExposure {
    long: number;
    short: number;
    gross: number;
    net: number;
}

export type RebalanceChangeAction = 'opening' | 'added' | 'removed' | 'increased' | 'reduced' | 'flipped';

export interface RebalancePositionChange {
    ticker: string;
    action: RebalanceChangeAction;
    beforeWeight: number | null;
    afterWeight: number | null;
    weightDelta: number;
    beforeDirection: 'Long' | 'Short' | null;
    afterDirection: 'Long' | 'Short' | null;
    currency: string | null;
    sector?: string | null;
    country?: string | null;
    priceAtChange: number | null;
    priceDate: string | null;
    ytdContribution: number | null;
}

export interface RebalanceChangeEvent {
    date: string;
    label: string;
    source: string;
    executionTiming?: string;
    status: 'active' | 'planned';
    changeCount: number;
    beforeExposure: RebalanceExposure | null;
    afterExposure: RebalanceExposure;
    changes: RebalancePositionChange[];
}

export interface RebalanceState {
    mode: 'static' | 'dated_snapshots';
    events: RebalanceEvent[];
    eventCount: number;
    history?: RebalanceChangeEvent[];
}

export interface CurrentBookScenario {
    scope?: string;
    period?: {
        startDate?: string;
        endDate?: string;
        years?: number;
    };
    beta?: number;
    annualReturn?: number;
    annualVolatility?: number;
    sharpe?: number;
    sortino?: number;
    maxDrawdown?: number;
    var95Daily?: number;
    cvar95Daily?: number;
}

export interface HistoryPoint {
    date: string;
    portfolio: number;
    portfolioGross?: number | null;
    benchmark: number;
    drawdown: number;
    beta?: number;
}

export interface AnalyticsHistoryPoint {
    date: string;
    portfolio: number | null;
    drawdown: number | null;
    variance: number | null;
    volatility: number | null;
    beta: number | null;
    // Cumulative long-book and short-book contribution on the same YTD basis as
    // ytdLongsContrib / ytdShortsContrib. They sum to the gross YTD path.
    longContribution: number | null;
    shortContribution: number | null;
    battingAverage: number | null;
    winnersCount: number;
    losersCount: number;
    positionsCount: number;
    profitFactor: number | null;
}


export interface CountryAllocation {
    long: number;
    short: number;
    contribution: number;
    tickers: { ticker: string; weight: number; type: string; contribution: number }[];
}

export interface RelativeStrength {
    ticker: string;
    rs: number;
    stock_ret: number;
    bmk_ret: number;
    bmk: string;
}

export interface CorrelationSurge {
    t1: string;
    t2: string;
    delta: number;
    c1m: number;
    c1y: number;
}

export interface MomentumMetrics {
    top_rs: RelativeStrength[];
    bot_rs: RelativeStrength[];
    corr_surges: CorrelationSurge[];
}

export interface FxExposure {
    exposure: number;
    pnl: number;
}

export interface BookAnalyticsPeriod {
    key: string;
    label: string;
    start: string;
    end: string;
    anchor: string | null;
    sessions: number;
    metrics: {
        battingAverage: number | null;
        winnersCount: number;
        losersCount: number;
        positionsCount: number;
        profitFactor: number | null;
        profitFactorInfinite?: boolean;
        winLossRatio: number | null;
        winLossRatioInfinite?: boolean;
        grossContribution?: number;
        best: { ticker: string; contribution: number } | null;
        worst: { ticker: string; contribution: number } | null;
        topGrossWeight: number | null;
        topGrossShare: number | null;
        grossExposure: number | null;
        topN?: number;
    };
}

/** Book analytics precomputed per window. Contributions are gross of financing
 *  and denominated in year-opening capital, which is what makes periods sum to
 *  the year. */
export interface BookAnalyticsReport {
    basis?: string;
    gross?: boolean;
    note?: string;
    periods?: BookAnalyticsPeriod[];
}

export interface FullRiskReport {
    vitals: Vitals;
    leverage: LeverageStats;
    activeRisks: RiskAttribution[];
    stressTests: StressTest[];
    history: HistoryPoint[];
    historyScope?: string;
    ytdHistory: HistoryPoint[];
    analyticsHistory: AnalyticsHistoryPoint[];
    periodicReturns: PeriodicReturn[];
    talebMetrics?: TalebMetrics;
    countryAllocation?: Record<string, CountryAllocation>;
    convexity: ConvexityMetrics | null;
    momentum: MomentumMetrics | null;
    fxExposures: Record<string, FxExposure>;
    rebalance?: RebalanceState;
    currentBookScenario?: CurrentBookScenario | null;
    bookAnalytics?: BookAnalyticsReport;
    error?: string;
}

export type CostTier = 'institutional' | 'retail' | 'none';

export const fetchDashboardData = async (retries = 5, delay = 3000, force = false, costTier: CostTier = 'retail', portfolioName: string = 'main'): Promise<FullRiskReport | null> => {
    for (let i = 0; i < retries; i++) {
        try {
            // Use relative path - Vite proxy will handle forwarding to backend
            const BASE_URL = import.meta.env.VITE_API_URL || '';
            const url = force
                ? `${BASE_URL}/api/metrics?force=true&costTier=${costTier}&portfolio=${portfolioName}&t=${new Date().getTime()}`
                : `${BASE_URL}/api/metrics?costTier=${costTier}&portfolio=${portfolioName}`;

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
                        currencyExposureNet: data.vitals.currencyExposureNet || data.vitals.currencyExposure || {},
                        currencyExposureGross: data.vitals.currencyExposureGross || {},
                        currencyExposureGrossShare: data.vitals.currencyExposureGrossShare || {},
                        fxWatchlist: data.vitals.fxWatchlist || {},
                        periodInfo: data.vitals.periodInfo || { Start_Date: "N/A", End_Date: "N/A", Years: 0 }
                    },
                    leverage: data.leverage || { Long_Exp: 0, Short_Exp: 0, Gross_Exp: 0, Net_Exp: 0, Daily_Drag: 0 },
                    history: data.history || [],
                    historyScope: data.historyScope,
                    analyticsHistory: data.analyticsHistory || [],
                    periodicReturns: data.periodicReturns || [],
                    activeRisks: data.riskAttribution || [], // Rename data.riskAttribution -> activeRisks
                    stressTests: data.stressTests || [],
                    ytdHistory: data.ytdHistory || [],
                    talebMetrics: data.talebMetrics,
                    countryAllocation: data.countryAllocation,
                    convexity: data.convexity || null,
                    momentum: data.momentum || null,
                    fxExposures: data.fxExposures || {},
                    rebalance: data.rebalance,
                    currentBookScenario: data.currentBookScenario || null,
                    bookAnalytics: data.bookAnalytics,
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
