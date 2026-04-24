import React, { useEffect, useState } from 'react';
import { fetchDashboardData } from '../utils/finance';
import type { FullRiskReport, CostTier } from '../utils/finance';
import { ExecutiveSummary } from './dashboard/ExecutiveSummary';
import { ReturnsHeatmap } from './dashboard/ReturnsHeatmap';
import { FxExposureWidget } from './dashboard/FxExposureWidget';
import { CountryMapWidget } from './dashboard/CountryMapWidget';
import { ConvexityWidget } from './dashboard/ConvexityWidget';
import { StockLookup } from './dashboard/StockLookup';
import { MoatWidget } from './dashboard/MoatWidget';
import { LayoutDashboard, ShieldCheck, RefreshCw, Clock } from 'lucide-react';
import { cn } from '../lib/utils';

export const Dashboard: React.FC = () => {
    const [data, setData] = useState<FullRiskReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [isSwitchingTier, setIsSwitchingTier] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [costTier, setCostTier] = useState<CostTier>('none');
    const [portfolioName, setPortfolioName] = useState<string>('main');

    useEffect(() => {
        const isInitialLoad = !data;
        if (isInitialLoad) setLoading(true);
        else setIsSwitchingTier(true);

        fetchDashboardData(5, 3000, isInitialLoad, costTier, portfolioName).then(res => {
            if (res) {
                if (res.error) {
                    setError(res.error);
                } else {
                    setData(res);
                }
            } else {
                setError("Failed to connect to backend API. Please check if the server is running.");
            }
        }).catch(err => {
            setError(err instanceof Error ? err.message : String(err));
        }).finally(() => {
            setLoading(false);
            setIsSwitchingTier(false);
        });
    }, [costTier, portfolioName]);

    const formatPercent = (val: number | undefined) => typeof val === 'number' ? `${(val * 100).toFixed(2)}%` : 'N/A';

    const [lastUpdated] = useState(() => new Date());

    if (loading) {
        return (
            <div className="min-h-screen bg-background text-foreground flex items-center justify-center">
                <div className="flex flex-col items-center gap-5">
                    <div className="animated-top-bar w-48 h-1 rounded-full opacity-80" />
                    <div className="h-10 w-10 animate-spin rounded-full border-2 border-white/10 border-t-white/60" />
                    <div className="flex flex-col items-center gap-1">
                        <p className="text-white font-semibold text-sm">Portfolio Intelligence</p>
                        <p className="text-gray-500 text-xs animate-pulse">Loading analytics engine…</p>
                    </div>
                </div>
            </div>
        )
    }

    if (error || !data) {
        return (
            <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-4">
                <div className="max-w-md w-full bg-rose-500/10 border border-rose-500/20 rounded-xl p-6 text-center">
                    <ShieldCheck className="h-12 w-12 text-rose-500 mx-auto mb-4" />
                    <h2 className="text-xl font-bold text-white mb-2">Dashboard Error</h2>
                    <p className="text-gray-300 mb-4">{error || "No data received from backend."}</p>
                    <button
                        onClick={() => window.location.reload()}
                        className="bg-rose-500 hover:bg-rose-600 text-white px-4 py-2 rounded-lg transition-colors"
                    >
                        Retry Connection
                    </button>
                    <div className="mt-4 text-xs text-gray-500 text-left bg-black/20 p-2 rounded overflow-auto max-h-32">
                        <p>Troubleshooting:</p>
                        <ul className="list-disc list-inside mt-1">
                            <li>Ensure the backend window is open</li>
                            <li>Check for errors in the backend console</li>
                            <li>Verify http://127.0.0.1:8000/api/metrics works in browser</li>
                        </ul>
                    </div>
                </div>
            </div>
        )
    }

    const { vitals, leverage, periodicReturns, countryAllocation, stressTests, convexity, ytdHistory } = data;

    const portfolioLabel = portfolioName === 'main' ? 'My Portfolio' : 'Szymon\'s Portfolio';

    return (
        <div className="min-h-screen bg-background text-foreground">
            {/* Animated top bar */}
            <div className="animated-top-bar h-[2px] w-full" />

            <div className="p-4 md:p-8">
            <div className="mx-auto max-w-[1600px] space-y-6 md:space-y-8">

                {/* Responsive Header */}
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div>
                        <h1 className="text-3xl md:text-4xl font-black tracking-tight text-white flex items-center gap-3">
                            <div className="p-2 bg-gradient-to-br from-indigo-500/20 to-blue-500/20 rounded-xl border border-white/10">
                                <LayoutDashboard className="h-6 w-6 md:h-7 md:w-7 text-indigo-400" />
                            </div>
                            <div className="flex flex-col">
                                <span className="bg-gradient-to-r from-white via-white to-gray-400 bg-clip-text text-transparent leading-none">
                                    {portfolioLabel}
                                </span>
                                <span className="text-[11px] font-normal text-gray-500 tracking-[0.12em] uppercase mt-1 flex items-center gap-1.5">
                                    <Clock className="h-3 w-3" />
                                    Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </span>
                            </div>
                        </h1>
                    </div>

                    {/* Header Controls */}
                    <div className="flex flex-wrap md:flex-nowrap items-center gap-3 text-sm w-full md:w-auto">

                        {/* Exposure Pills */}
                        <div className="flex items-center gap-2">
                            <FxExposureWidget vitals={vitals} periodLabel={vitals?.periodLabel ?? "YTD"} />
                            <div className="flex bg-gradient-to-br from-emerald-500/10 to-emerald-900/20 px-3 py-2 rounded-xl border border-emerald-500/20 backdrop-blur-md flex-col justify-center shadow-lg shadow-emerald-500/5 transition-all hover:scale-105 hover:border-emerald-500/40">
                                <p className="text-[9px] uppercase tracking-wider text-emerald-500/70 font-bold mb-0.5">Long Exp</p>
                                <p className="font-mono text-emerald-400 font-black text-sm leading-none">{formatPercent(leverage.Long_Exp)}</p>
                            </div>
                            <div className="flex bg-gradient-to-br from-rose-500/10 to-rose-900/20 px-3 py-2 rounded-xl border border-rose-500/20 backdrop-blur-md flex-col justify-center shadow-lg shadow-rose-500/5 transition-all hover:scale-105 hover:border-rose-500/40">
                                <p className="text-[9px] uppercase tracking-wider text-rose-500/70 font-bold mb-0.5">Short Exp</p>
                                <p className="font-mono text-rose-400 font-black text-sm leading-none">{formatPercent(leverage.Short_Exp)}</p>
                            </div>
                        </div>

                        {/* Divider */}
                        <div className="hidden md:block w-px h-8 bg-white/10" />

                        {/* Portfolio Switcher */}
                        <div className="flex bg-white/5 rounded-lg border border-white/10 p-1 relative h-[38px]">
                            {(['main', 'szymon'] as const).map(portfolio => (
                                <button
                                    key={portfolio}
                                    onClick={() => setPortfolioName(portfolio)}
                                    disabled={isSwitchingTier}
                                    className={cn(
                                        "px-3 py-1 text-[10px] sm:text-xs font-semibold uppercase tracking-wider rounded-md transition-all whitespace-nowrap",
                                        portfolioName === portfolio
                                            ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                                            : "text-gray-500 hover:text-gray-300 hover:bg-white/5 border border-transparent",
                                        isSwitchingTier ? "opacity-50 cursor-not-allowed" : ""
                                    )}
                                >
                                    {portfolio === 'main' ? 'My Portfolio' : 'Szymon'}
                                </button>
                            ))}
                        </div>

                        {/* Cost Tier Toggle & Refresh Wrapper */}
                        <div className="flex w-full md:w-auto items-center gap-3 mt-2 md:mt-0">
                            <div className="flex-1 md:flex-none flex bg-white/5 rounded-lg border border-white/10 p-1 relative h-[38px]">
                                {isSwitchingTier && (
                                    <div className="absolute -top-1 -right-1 flex h-3 w-3">
                                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                                        <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                                    </div>
                                )}
                                {(['institutional', 'retail', 'none'] as const).map(tier => (
                                    <button
                                        key={tier}
                                        onClick={() => setCostTier(tier)}
                                        disabled={isSwitchingTier}
                                        className={cn(
                                            "flex-1 md:flex-none px-2 sm:px-3 py-1 text-[10px] sm:text-xs font-semibold uppercase tracking-wider rounded-md transition-all whitespace-nowrap",
                                            costTier === tier 
                                                ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30" 
                                                : "text-gray-500 hover:text-gray-300 hover:bg-white/5 border border-transparent",
                                            isSwitchingTier ? "opacity-50 cursor-not-allowed" : ""
                                        )}
                                    >
                                        {tier === 'none' ? 'No Drag' : tier}
                                    </button>
                                ))}
                            </div>

                            {/* Refresh Button */}
                            <button
                                onClick={() => {
                                    setIsSwitchingTier(true);
                                    fetchDashboardData(5, 1000, true, costTier, portfolioName).then(res => { // force=true
                                        if (res) setData(res);
                                    }).finally(() => setIsSwitchingTier(false));
                                }}
                                className="bg-white/5 hover:bg-white/10 w-[38px] h-[38px] rounded-lg border border-white/10 transition-colors flex items-center justify-center shrink-0"
                                title="Force Refresh Data"
                            >
                                <RefreshCw className={cn("h-4 w-4 text-emerald-400", isSwitchingTier ? "animate-spin" : "")} />
                            </button>
                        </div>
                    </div>
                </div>

                {/* NEW: ExecutiveSummary (YTD Returns, Alpha, Benchmarks, Financing, Stress Tests) */}
                <ExecutiveSummary vitals={vitals} costTier={costTier} ytdHistory={ytdHistory} stressTests={stressTests} momentum={data.momentum} />

                {/* ROW 1.5: Convexity Analysis */}
                <ConvexityWidget convexity={convexity} />

                {/* ROW 2: Returns Heatmap & Portfolio Contribution (Full Width) */}
                <ReturnsHeatmap periodicReturns={periodicReturns} periodLabel={vitals?.periodLabel ?? "YTD"} />

                {/* ROW 3: World Map (Full Width) */}
                <CountryMapWidget countryAllocation={countryAllocation} />

                {/* ROW 4: Business Quality — Munger Lens */}
                <MoatWidget portfolioName={portfolioName} />

                {/* ROW 5: Stock Lookup */}
                <StockLookup />
            </div>
            </div>
        </div>
    );
};
