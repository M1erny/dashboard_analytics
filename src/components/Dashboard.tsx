import React, { useEffect, useState, useCallback, Suspense, lazy } from 'react';
import { fetchDashboardData } from '../utils/finance';
import type { FullRiskReport, CostTier } from '../utils/finance';
import { ExecutiveSummary } from './dashboard/ExecutiveSummary';
import { ReturnsHeatmap } from './dashboard/ReturnsHeatmap';
import { FxExposureWidget } from './dashboard/FxExposureWidget';
import { ConvexityWidget } from './dashboard/ConvexityWidget';
import { LayoutDashboard, ShieldCheck, RefreshCw, Clock, CircleDollarSign } from 'lucide-react';
import { cn } from '../lib/utils';

// ─── Lazy-loaded below-the-fold widgets ──────────────────────
// These are code-split into separate chunks, loaded only when
// the user scrolls past the ExecutiveSummary + ReturnsHeatmap.
const CountryMapWidget = lazy(() => import('./dashboard/CountryMapWidget').then(m => ({ default: m.CountryMapWidget })));
// ConvexityWidget is statically imported (also used inside ExecutiveSummary compact view)
const StockLookup = lazy(() => import('./dashboard/StockLookup').then(m => ({ default: m.StockLookup })));
const MoatWidget = lazy(() => import('./dashboard/MoatWidget').then(m => ({ default: m.MoatWidget })));

// ─── Suspense fallback skeleton ──────────────────────────────
const WidgetSkeleton = ({ height = 'h-[300px]' }: { height?: string }) => (
    <div className={cn(
        "rounded-2xl border border-white/[0.06] bg-gradient-to-b from-slate-900/60 to-slate-950/80",
        "flex items-center justify-center animate-pulse",
        height
    )}>
        <div className="flex flex-col items-center gap-3">
            <div className="h-6 w-6 rounded-full border-2 border-white/10 border-t-white/40 animate-spin" />
            <span className="text-[11px] text-gray-600 uppercase tracking-widest">Loading widget...</span>
        </div>
    </div>
);

// ─── Quotes (static, outside component) ──────────────────────
const QUOTES = [
    // Warren Buffett — 2
    { text: "The stock market is a no-called-strike game. You don't have to swing at everything — you can wait for your pitch. The problem when you're a money manager is that your fans keep yelling, 'Swing, you bum!'", author: "Warren Buffett" },
    { text: "It is far better to buy a wonderful company at a fair price than a fair company at a wonderful price.", author: "Warren Buffett" },
    // Charlie Munger — 2
    { text: "The big money is not in the buying and the selling, but in the waiting.", author: "Charlie Munger" },
    { text: "It is remarkable how much long-term advantage people like us have gotten by trying to be consistently not stupid, instead of trying to be very intelligent.", author: "Charlie Munger" },
    // Ben Graham — 2
    { text: "In the short run, the market is a voting machine, but in the long run, it is a weighing machine.", author: "Ben Graham" },
    { text: "The investor's chief problem — and even his worst enemy — is likely to be himself.", author: "Ben Graham" },
    // Howard Marks — 2
    { text: "You can't predict. You can prepare.", author: "Howard Marks" },
    { text: "The most dangerous thing is to buy something at the peak of its popularity. At that point, all favorable facts and opinions are already factored into its price, and no new buyers are left to emerge.", author: "Howard Marks" },
    // Jeff Bezos — 2
    { text: "Your margin is my opportunity.", author: "Jeff Bezos" },
    { text: "We are stubborn on vision. We are flexible on details.", author: "Jeff Bezos" },
    // Elon Musk — 2
    { text: "When something is important enough, you do it even if the odds are not in your favor.", author: "Elon Musk" },
    { text: "Constantly seek criticism. A well thought out critique of whatever you're doing is as valuable as gold.", author: "Elon Musk" },
    // Richard Dawkins — 2
    { text: "The essence of life is statistical improbability on a colossal scale.", author: "Richard Dawkins" },
    { text: "We are survival machines — robot vehicles blindly programmed to preserve the selfish molecules known as genes.", author: "Richard Dawkins" },
];

// ─── Author color map (pure function, outside component) ─────
const getAuthorColors = (author: string) => {
    switch(author) {
        case 'Warren Buffett': return { color: 'text-amber-500/30', bg: 'bg-amber-500/50', text: 'text-amber-400', dot: 'bg-amber-400' };
        case 'Charlie Munger': return { color: 'text-emerald-500/30', bg: 'bg-emerald-500/50', text: 'text-emerald-400', dot: 'bg-emerald-400' };
        case 'Ben Graham': return { color: 'text-slate-400/30', bg: 'bg-slate-400/50', text: 'text-slate-300', dot: 'bg-slate-400' };
        case 'Howard Marks': return { color: 'text-violet-500/30', bg: 'bg-violet-500/50', text: 'text-violet-400', dot: 'bg-violet-400' };
        case 'Jeff Bezos': return { color: 'text-orange-500/30', bg: 'bg-orange-500/50', text: 'text-orange-400', dot: 'bg-orange-400' };
        case 'Elon Musk': return { color: 'text-red-500/30', bg: 'bg-red-500/50', text: 'text-red-400', dot: 'bg-red-400' };
        case 'Richard Dawkins': return { color: 'text-blue-500/30', bg: 'bg-blue-500/50', text: 'text-blue-400', dot: 'bg-blue-400' };
        default: return { color: 'text-indigo-500/30', bg: 'bg-indigo-500/50', text: 'text-indigo-400', dot: 'bg-indigo-400' };
    }
};

const COST_TIER_OPTIONS: { value: CostTier; label: string; short: string }[] = [
    { value: 'retail', label: 'Retail', short: 'Ret.' },
    { value: 'institutional', label: 'Institutional', short: 'Inst.' },
    { value: 'none', label: 'No Drag', short: 'None' },
];

export const Dashboard: React.FC = () => {
    const [data, setData] = useState<FullRiskReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [isSwitchingTier, setIsSwitchingTier] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [costTier, setCostTier] = useState<CostTier>('retail');
    const portfolioName: string = 'main';

    useEffect(() => {
        const isInitialLoad = !data;
        if (isInitialLoad) setLoading(true);
        else setIsSwitchingTier(true);

        fetchDashboardData(5, 3000, false, costTier, portfolioName).then(res => {
            if (res) {
                if (res.error) {
                    setError(res.error);
                } else {
                    setData(res);
                    setError(null);
                    setLastUpdated(new Date());
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

    // Memoized formatter — avoids re-creation on every render
    const formatPercent = useCallback(
        (val: number | undefined) => typeof val === 'number' ? `${(val * 100).toFixed(2)}%` : 'N/A',
        []
    );

    const [lastUpdated, setLastUpdated] = useState(() => new Date());
    const [quoteIdx, setQuoteIdx] = useState(() => Math.floor(Math.random() * QUOTES.length));
    const [quoteVisible, setQuoteVisible] = useState(true);

    // Cycle quotes every 15 seconds while loading
    useEffect(() => {
        if (!loading) return;
        const interval = setInterval(() => {
            setQuoteVisible(false);
            setTimeout(() => {
                setQuoteIdx(i => (i + 1) % QUOTES.length);
                setQuoteVisible(true);
            }, 400);
        }, 15000);
        return () => clearInterval(interval);
    }, [loading]);

    if (loading) {
        const quote = QUOTES[quoteIdx];
        const colors = getAuthorColors(quote.author);

        return (
            <div className="min-h-screen bg-background text-foreground flex flex-col items-center justify-center px-6 relative overflow-hidden">
                {/* Ambient glow blobs */}
                <div className="absolute top-1/3 left-1/4 w-96 h-96 rounded-full bg-indigo-600/5 blur-3xl pointer-events-none" />
                <div className="absolute bottom-1/3 right-1/4 w-80 h-80 rounded-full bg-emerald-600/5 blur-3xl pointer-events-none" />

                <div className="flex flex-col items-center gap-8 max-w-xl w-full">

                    {/* Logo / Brand */}
                    <div className="flex flex-col items-center gap-3">
                        <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500/20 to-blue-500/20 border border-white/10 shadow-2xl shadow-indigo-500/10">
                            <LayoutDashboard className="h-7 w-7 text-indigo-400" />
                        </div>
                        <div className="text-center">
                            <p className="text-white font-black text-lg tracking-tight">Portfolio Intelligence</p>
                            <p className="text-gray-500 text-xs tracking-[0.15em] uppercase mt-0.5">Loading analytics engine...</p>
                        </div>
                    </div>

                    {/* Quote card */}
                    <div
                        className="w-full rounded-2xl border border-white/[0.07] bg-white/[0.03] backdrop-blur-xl p-7 text-center flex flex-col justify-between min-h-[260px]"
                        style={{
                            transition: 'opacity 0.4s ease, transform 0.4s ease',
                            opacity: quoteVisible ? 1 : 0,
                            transform: quoteVisible ? 'translateY(0)' : 'translateY(6px)',
                        }}
                    >
                        {/* Open-quote mark */}
                        <div className={cn(
                            "text-5xl font-black leading-none mb-3 select-none",
                            colors.color
                        )}>
                            &ldquo;
                        </div>

                        <div className="flex-1 flex items-center justify-center">
                            <p className="text-gray-200 text-[15px] font-medium leading-relaxed tracking-[0.01em]">
                                {quote.text}
                            </p>
                        </div>

                        {/* Attribution */}
                        <div className="flex items-center justify-center gap-2 mt-5">
                            <div className={cn(
                                "w-6 h-[1px]",
                                colors.bg
                            )} />
                            <span className={cn(
                                "text-[11px] font-bold uppercase tracking-[0.18em]",
                                colors.text
                            )}>
                                {quote.author}
                            </span>
                            <div className={cn(
                                "w-6 h-[1px]",
                                colors.bg
                            )} />
                        </div>
                    </div>

                    {/* Progress dots */}
                    <div className="flex flex-wrap justify-center items-center gap-2 max-w-md">
                        {QUOTES.map((q, i) => {
                            const c = getAuthorColors(q.author);
                            return (
                                <div
                                    key={i}
                                    className={cn(
                                        "rounded-full transition-all duration-300",
                                        i === quoteIdx
                                            ? `w-5 h-1.5 ${c.dot}`
                                            : "w-1.5 h-1.5 bg-white/10"
                                    )}
                                />
                            );
                        })}
                    </div>

                    {/* Spinner */}
                    <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/10 border-t-white/50" />
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

    const { vitals, leverage, periodicReturns, activeRisks, countryAllocation, stressTests, convexity, ytdHistory } = data;

    const portfolioLabel = 'My Portfolio';

    return (
        <div className="min-h-screen bg-background text-foreground">
            {/* Animated top bar */}
            <div className="animated-top-bar h-[2px] w-full" />

            <div className="px-4 py-5 sm:px-5 md:p-8">
            <div className="mx-auto max-w-[1600px] space-y-6 md:space-y-8">

                {/* Responsive Header */}
                <div className="flex flex-col xl:flex-row xl:items-start justify-between gap-5 md:gap-6">
                    <div className="min-w-0">
                        <h1 className="text-3xl md:text-4xl font-black tracking-tight text-white flex items-center gap-3 min-w-0">
                            <div className="p-2 bg-gradient-to-br from-indigo-500/20 to-blue-500/20 rounded-xl border border-white/10 shrink-0">
                                <LayoutDashboard className="h-6 w-6 md:h-7 md:w-7 text-indigo-400" />
                            </div>
                            <div className="flex flex-col min-w-0">
                                <span className="bg-gradient-to-r from-white via-white to-gray-400 bg-clip-text text-transparent leading-none truncate">
                                    {portfolioLabel}
                                </span>
                                <span className="text-[11px] font-normal text-gray-500 tracking-[0.12em] uppercase mt-1 flex items-center gap-1.5 whitespace-nowrap">
                                    <Clock className="h-3 w-3" />
                                    Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </span>
                            </div>
                        </h1>
                    </div>

                    {/* Header Controls */}
                    <div className="flex flex-col sm:flex-row sm:flex-wrap xl:flex-nowrap items-stretch sm:items-center gap-3 text-sm w-full xl:w-auto">

                        {/* Exposure Pills */}
                        <div className="grid grid-cols-2 sm:flex items-stretch gap-2 w-full xl:w-auto">
                            <div className="col-span-2 sm:col-span-1">
                                <FxExposureWidget vitals={vitals} periodLabel={vitals?.periodLabel ?? "YTD"} />
                            </div>
                            <div className="flex min-h-[56px] bg-gradient-to-br from-emerald-500/10 to-emerald-900/20 px-3 py-2 rounded-xl border border-emerald-500/20 backdrop-blur-md flex-col justify-center shadow-lg shadow-emerald-500/5 transition-all hover:scale-[1.02] hover:border-emerald-500/40">
                                <p className="text-[9px] uppercase tracking-wider text-emerald-500/70 font-bold mb-0.5">Long Exposure</p>
                                <p className="font-mono text-emerald-400 font-black text-sm leading-none">{formatPercent(leverage.Long_Exp)}</p>
                            </div>
                            <div className="flex min-h-[56px] bg-gradient-to-br from-rose-500/10 to-rose-900/20 px-3 py-2 rounded-xl border border-rose-500/20 backdrop-blur-md flex-col justify-center shadow-lg shadow-rose-500/5 transition-all hover:scale-[1.02] hover:border-rose-500/40">
                                <p className="text-[9px] uppercase tracking-wider text-rose-500/70 font-bold mb-0.5">Short Exposure</p>
                                <p className="font-mono text-rose-400 font-black text-sm leading-none">{formatPercent(leverage.Short_Exp)}</p>
                            </div>
                        </div>



                        {/* Cost Tier Toggle & Refresh Wrapper */}
                        <div className="flex w-full sm:w-auto items-center gap-3">

                            <div className="flex flex-1 sm:flex-none items-center rounded-lg border border-white/10 bg-white/[0.04] p-1 h-[38px] min-w-0">
                                <CircleDollarSign className="h-4 w-4 text-amber-400 mx-2 hidden sm:block" />
                                {COST_TIER_OPTIONS.map(option => {
                                    const active = costTier === option.value;
                                    return (
                                        <button
                                            key={option.value}
                                            onClick={() => setCostTier(option.value)}
                                            className={cn(
                                                "h-7 flex-1 sm:flex-none px-2.5 rounded-md text-[11px] font-bold uppercase tracking-[0.08em] transition-colors whitespace-nowrap",
                                                active
                                                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                                    : "text-gray-500 hover:text-gray-300 hover:bg-white/[0.04]"
                                            )}
                                            title={`${option.label} financing assumptions`}
                                        >
                                            <span className="hidden sm:inline">{option.label}</span>
                                            <span className="sm:hidden">{option.short}</span>
                                        </button>
                                    );
                                })}
                            </div>

                            {/* Refresh Button */}
                            <button
                                onClick={() => {
                                    setIsSwitchingTier(true);
                                    fetchDashboardData(5, 1000, true, costTier, portfolioName).then(res => { // force=true
                                        if (res) {
                                            setData(res);
                                            setError(res.error || null);
                                            if (!res.error) setLastUpdated(new Date());
                                        }
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
                <ExecutiveSummary vitals={vitals} costTier={costTier} ytdHistory={ytdHistory} stressTests={stressTests} momentum={data.momentum} convexity={convexity} />

                {/* ROW 1.5: Returns Heatmap & Portfolio Contribution (Full Width) */}
                <ReturnsHeatmap periodicReturns={periodicReturns} activeRisks={activeRisks} periodLabel={vitals?.periodLabel ?? "YTD"} />

                {/* ROW 2: Convexity Analysis */}
                <ConvexityWidget convexity={convexity} />

                {/* ROW 3: World Map (Full Width, lazy-loaded — heaviest widget) */}
                <Suspense fallback={<WidgetSkeleton height="h-[450px]" />}>
                    <CountryMapWidget countryAllocation={countryAllocation} />
                </Suspense>

                {/* ROW 4: Business Quality — Munger Lens (lazy-loaded, makes own API call) */}
                <Suspense fallback={<WidgetSkeleton height="h-[300px]" />}>
                    <MoatWidget portfolioName={portfolioName} />
                </Suspense>

                {/* ROW 5: Stock Lookup (lazy-loaded, interactive tool) */}
                <Suspense fallback={<WidgetSkeleton height="h-[200px]" />}>
                    <StockLookup />
                </Suspense>
            </div>
            </div>
        </div>
    );
};
