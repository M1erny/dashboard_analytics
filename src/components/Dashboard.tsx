import React, { useEffect, useState, useCallback, Suspense, lazy } from 'react';
import { fetchDashboardData } from '../utils/finance';
import type { FullRiskReport, CostTier, RebalanceChangeAction, RebalancePositionChange, RebalanceState } from '../utils/finance';
import { ExecutiveSummary } from './dashboard/ExecutiveSummary';
import { ReturnsHeatmap } from './dashboard/ReturnsHeatmap';
import { FxExposureWidget } from './dashboard/FxExposureWidget';
import { ConvexityWidget } from './dashboard/ConvexityWidget';
import { HistoricalDiagnostics } from './dashboard/HistoricalDiagnostics';
import {
    LayoutDashboard, ShieldCheck, RefreshCw, Clock, CircleDollarSign, Store,
    Building2, Ban, BrainCircuit, GitBranch, X, CalendarDays, Plus, Minus,
    Trash2, ArrowRightLeft, type LucideIcon
} from 'lucide-react';
import { cn } from '../lib/utils';

// ─── Lazy-loaded below-the-fold widgets ──────────────────────
// These are code-split into separate chunks, loaded only when
// the user scrolls past the ExecutiveSummary + ReturnsHeatmap.
const CountryMapWidget = lazy(() => import('./dashboard/CountryMapWidget').then(m => ({ default: m.CountryMapWidget })));
// ConvexityWidget is statically imported (also used inside ExecutiveSummary compact view)

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

const COST_TIER_OPTIONS: { value: CostTier; label: string; short: string; Icon: LucideIcon; title: string }[] = [
    { value: 'retail', label: 'Retail', short: 'Ret.', Icon: Store, title: 'Retail financing assumptions' },
    { value: 'institutional', label: 'Institutional', short: 'Inst.', Icon: Building2, title: 'Institutional financing assumptions' },
    { value: 'none', label: 'No Drag', short: 'No Drag', Icon: Ban, title: 'No financing drag scenario' },
];

const formatBookPercent = (value: number | null | undefined, decimals = 1) =>
    typeof value === 'number' ? `${(value * 100).toFixed(decimals)}%` : '--';

const formatBookDelta = (value: number | null | undefined) => {
    if (typeof value !== 'number') return '--';
    const sign = value > 0 ? '+' : '';
    return `${sign}${(value * 100).toFixed(1)}pp`;
};

const exposureDeltaClass = (value: number) => {
    if (Math.abs(value) < 0.0005) return 'text-gray-500';
    return value > 0 ? 'text-amber-300' : 'text-sky-300';
};

const formatBookContribution = (value: number | null | undefined) => {
    if (typeof value !== 'number') return '--';
    const sign = value > 0 ? '+' : '';
    return `${sign}${(value * 100).toFixed(2)}%`;
};

const formatBookPrice = (change: RebalancePositionChange) => {
    if (typeof change.priceAtChange !== 'number') return '--';
    const decimals = Math.abs(change.priceAtChange) >= 1000 ? 0 : 2;
    return `${change.currency ?? ''} ${change.priceAtChange.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    })}`.trim();
};

const actionMeta: Record<RebalanceChangeAction, { label: string; Icon: LucideIcon; className: string }> = {
    opening: { label: 'Opening', Icon: GitBranch, className: 'border-sky-500/20 bg-sky-500/10 text-sky-300' },
    added: { label: 'Added', Icon: Plus, className: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' },
    increased: { label: 'Increased', Icon: Plus, className: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' },
    reduced: { label: 'Reduced', Icon: Minus, className: 'border-amber-500/20 bg-amber-500/10 text-amber-300' },
    removed: { label: 'Deleted', Icon: Trash2, className: 'border-rose-500/20 bg-rose-500/10 text-rose-300' },
    flipped: { label: 'Flipped', Icon: ArrowRightLeft, className: 'border-violet-500/20 bg-violet-500/10 text-violet-300' },
};

const RebalanceHistoryModal = ({ rebalance, open, onClose }: {
    rebalance?: RebalanceState;
    open: boolean;
    onClose: () => void;
}) => {
    // Must sit above the early return: this component has no other hooks, so registering
    // it conditionally would change hook order every time the modal opens or closes.
    useEffect(() => {
        if (!open) return;
        const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [open, onClose]);

    if (!open) return null;

    const history = rebalance?.history ?? [];
    const activeCount = history.filter(event => event.status === 'active').length;
    const plannedCount = history.filter(event => event.status === 'planned').length;
    const activeLabel = activeCount === 1 ? 'active book' : 'active books';

    return (
        <div
            className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 px-3 py-5 backdrop-blur-md sm:px-5 md:py-8"
            onClick={onClose}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="rebalance-history-title"
                onClick={event => event.stopPropagation()}
                className="flex max-h-[calc(100vh-40px)] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-white/[0.1] bg-slate-950 shadow-2xl shadow-black/60"
            >
                <div className="flex flex-col gap-4 border-b border-white/[0.08] bg-white/[0.035] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                    <div className="min-w-0">
                        <div className="flex items-center gap-2">
                            <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-sky-500/20 bg-sky-500/10">
                                <GitBranch className="h-4 w-4 text-sky-300" />
                            </span>
                            <div>
                                <h2 id="rebalance-history-title" className="text-base font-black tracking-tight text-white">Dated Book History</h2>
                                <p className="text-[11px] uppercase tracking-[0.12em] text-gray-500">
                                    {activeCount} {activeLabel} / {plannedCount} planned
                                </p>
                            </div>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-gray-400 transition-colors hover:bg-white/[0.08] hover:text-white"
                        aria-label="Close dated book history"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div className="overflow-y-auto px-4 py-4 sm:px-5">
                    {history.length === 0 ? (
                        <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-5 text-sm text-gray-400">
                            No dated-book history is available yet.
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {history.map((event, eventIndex) => (
                                <section key={`${event.date}-${event.label}`} className="rounded-xl border border-white/[0.08] bg-white/[0.025]">
                                    <div className="flex flex-col gap-3 border-b border-white/[0.06] px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
                                        <div className="flex min-w-0 items-start gap-3">
                                            <span className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-gray-300">
                                                <CalendarDays className="h-4 w-4" />
                                            </span>
                                            <div className="min-w-0">
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <h3 className="truncate text-sm font-bold text-white">{event.label}</h3>
                                                    <span className={cn(
                                                        "rounded-md border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.12em]",
                                                        event.status === 'active'
                                                            ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
                                                            : "border-amber-500/20 bg-amber-500/10 text-amber-300"
                                                    )}>
                                                        {event.status}
                                                    </span>
                                                </div>
                                                <p className="mt-1 text-[11px] text-gray-500">
                                                    Moment of change: <span className="font-mono text-gray-300">{event.date}</span>
                                                </p>
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
                                            <div className="rounded-lg bg-white/[0.035] px-3 py-2">
                                                <p className="uppercase tracking-[0.12em] text-gray-600">Long</p>
                                                <p className="font-mono font-bold text-emerald-300">{formatBookPercent(event.afterExposure.long)}</p>
                                            </div>
                                            <div className="rounded-lg bg-white/[0.035] px-3 py-2">
                                                <p className="uppercase tracking-[0.12em] text-gray-600">Short</p>
                                                <p className="font-mono font-bold text-rose-300">{formatBookPercent(event.afterExposure.short)}</p>
                                            </div>
                                            <div className="rounded-lg bg-white/[0.035] px-3 py-2">
                                                <p className="uppercase tracking-[0.12em] text-gray-600">Gross</p>
                                                <p className="font-mono font-bold text-gray-200">{formatBookPercent(event.afterExposure.gross)}</p>
                                            </div>
                                            <div className="rounded-lg bg-white/[0.035] px-3 py-2">
                                                <p className="uppercase tracking-[0.12em] text-gray-600">Changes</p>
                                                <p className="font-mono font-bold text-sky-300">{event.changeCount}</p>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="divide-y divide-white/[0.045]">
                                        {event.changes.length === 0 ? (
                                            <div className="px-4 py-4 text-sm text-gray-500">
                                                No position-level changes versus the previous dated book.
                                            </div>
                                        ) : event.changes.map(change => {
                                            const meta = actionMeta[change.action];
                                            const Icon = meta.Icon;
                                            const directionText = change.beforeDirection && change.afterDirection && change.beforeDirection !== change.afterDirection
                                                ? `${change.beforeDirection} -> ${change.afterDirection}`
                                                : (change.afterDirection ?? change.beforeDirection ?? '--');

                                            return (
                                                <div key={`${event.date}-${change.ticker}-${change.action}`} className="grid grid-cols-1 gap-3 px-4 py-3 text-sm md:grid-cols-[150px_1fr_150px_170px_140px] md:items-center">
                                                    <div className={cn("inline-flex w-fit items-center gap-1.5 rounded-lg border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.1em]", meta.className)}>
                                                        <Icon className="h-3 w-3" />
                                                        {meta.label}
                                                    </div>
                                                    <div className="min-w-0">
                                                        <div className="flex flex-wrap items-baseline gap-2">
                                                            <span className="font-mono text-sm font-black tracking-wide text-white">{change.ticker}</span>
                                                            <span className="text-[11px] text-gray-500">{directionText}</span>
                                                        </div>
                                                        <p className="mt-0.5 truncate text-[11px] text-gray-600">{change.sector ?? 'Unknown'} / {change.country ?? 'n/a'}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-[10px] uppercase tracking-[0.12em] text-gray-600">Size</p>
                                                        <p className="font-mono text-[12px] font-bold text-gray-300">
                                                            {formatBookPercent(change.beforeWeight)} &rarr; {formatBookPercent(change.afterWeight)}
                                                        </p>
                                                        <p className={cn(
                                                            "font-mono text-[11px]",
                                                            change.weightDelta > 0 ? "text-emerald-400" : change.weightDelta < 0 ? "text-rose-400" : "text-gray-500"
                                                        )}>
                                                            {formatBookDelta(change.weightDelta)}
                                                        </p>
                                                    </div>
                                                    <div>
                                                        <p className="text-[10px] uppercase tracking-[0.12em] text-gray-600">Price</p>
                                                        <p className="font-mono text-[12px] font-bold text-gray-300">{formatBookPrice(change)}</p>
                                                        <p className="font-mono text-[10px] text-gray-600">{change.priceDate ?? event.date}</p>
                                                    </div>
                                                    <div>
                                                        <p className="text-[10px] uppercase tracking-[0.12em] text-gray-600">Contribution</p>
                                                        <p className={cn(
                                                            "font-mono text-[12px] font-bold",
                                                            (change.ytdContribution ?? 0) > 0 ? "text-emerald-400" : (change.ytdContribution ?? 0) < 0 ? "text-rose-400" : "text-gray-500"
                                                        )}>
                                                            {formatBookContribution(change.ytdContribution)}
                                                        </p>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>

                                    {event.status === 'planned' && eventIndex > 0 && (
                                        <div className="border-t border-amber-500/10 bg-amber-500/[0.035] px-4 py-2 text-[11px] text-amber-200/70">
                                            Planned book: contribution starts counting from this effective date, so previous YTD stays chained to the earlier book.
                                        </div>
                                    )}
                                </section>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export const Dashboard: React.FC = () => {
    const [data, setData] = useState<FullRiskReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [isSwitchingTier, setIsSwitchingTier] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // Kept separate from `error`: a failed manual refresh must not trip the full-screen
    // error card and throw away a dashboard that is still perfectly readable.
    const [refreshError, setRefreshError] = useState<string | null>(null);
    const [costTier, setCostTier] = useState<CostTier>('none');
    const [lastUpdated, setLastUpdated] = useState(() => new Date());
    const [showRebalanceHistory, setShowRebalanceHistory] = useState(false);
    const portfolioName: string = 'main';

    useEffect(() => {
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

    const [quoteIdx, setQuoteIdx] = useState(() => Math.floor(Math.random() * QUOTES.length));
    const [quoteVisible, setQuoteVisible] = useState(true);
    // A cold /api/metrics can legitimately take ~20s, and finance.ts retries it up to five
    // times. Without a clock there is no way to tell a slow load from a dead one.
    const [loadElapsed, setLoadElapsed] = useState(0);

    useEffect(() => {
        if (!loading) return;
        const startedAt = Date.now();
        const interval = setInterval(() => setLoadElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000);
        return () => { clearInterval(interval); setLoadElapsed(0); };
    }, [loading]);

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
                            <p className="text-gray-500 text-xs tracking-[0.15em] uppercase mt-0.5">
                                Loading analytics engine... <span className="tabular-nums text-gray-400">{loadElapsed}s</span>
                            </p>
                            {loadElapsed >= 30 && (
                                <p className="mt-1.5 text-[11px] text-amber-200/60">Taking longer than usual — still retrying.</p>
                            )}
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

    const { vitals, leverage, periodicReturns, activeRisks, countryAllocation, stressTests, convexity, ytdHistory, analyticsHistory, rebalance } = data;
    const rebalanceActive = rebalance?.mode === 'dated_snapshots';
    const latestRebalanceEvent = rebalance?.events?.[rebalance.events.length - 1];
    const januaryExposure = rebalance?.history?.[0]?.afterExposure;
    const sumCurrentBookExposure = (direction: 'Long' | 'Short') => {
        let total = 0;
        let hasRows = false;
        for (const row of periodicReturns) {
            if (row.direction !== direction) continue;
            if (row.status && row.status !== 'Active') continue;
            const weight = typeof row.currentWeight === 'number' ? row.currentWeight : row.weight;
            if (typeof weight !== 'number') continue;
            total += Math.abs(weight);
            hasRows = true;
        }
        return hasRows ? total : undefined;
    };
    const currentLongExposure = sumCurrentBookExposure('Long') ?? leverage.Long_Exp;
    const currentShortExposure = sumCurrentBookExposure('Short') ?? leverage.Short_Exp;
    const januaryLongExposure = januaryExposure?.long ?? leverage.Long_Exp;
    const januaryShortExposure = januaryExposure?.short ?? leverage.Short_Exp;
    const longExposureDelta = currentLongExposure - januaryLongExposure;
    const shortExposureDelta = currentShortExposure - januaryShortExposure;
    const currentNetExposure = currentLongExposure - currentShortExposure;
    const januaryNetExposure = januaryLongExposure - januaryShortExposure;
    const netExposureDelta = currentNetExposure - januaryNetExposure;
    const currentGrossExposure = currentLongExposure + currentShortExposure;
    const januaryGrossExposure = januaryLongExposure + januaryShortExposure;
    const grossExposureDelta = currentGrossExposure - januaryGrossExposure;
    const netStanceLabel = netExposureDelta > 0.005
        ? 'More net long'
        : netExposureDelta < -0.005
            ? 'Less net long'
            : 'Net stance flat';
    const leverageStanceLabel = grossExposureDelta > 0.005
        ? 'more levered'
        : grossExposureDelta < -0.005
            ? 'less levered'
            : 'same leverage';

    const portfolioLabel = 'My Portfolio';

    return (
        <div className="min-h-screen bg-background text-foreground">
            {/* Animated top bar */}
            <div className="animated-top-bar h-[2px] w-full" />

            <div className="px-4 py-5 sm:px-5 md:p-8">
            {/* While a tier refetch is in flight the figures below still belong to the previous
                tier, but the tier badge already reads the new one. Dim them so the mismatch
                cannot be mistaken for a recomputed book. */}
            <div
                aria-busy={isSwitchingTier}
                className={cn(
                    "mx-auto max-w-[1600px] space-y-6 md:space-y-8",
                    // Everything except the header (the first child) is stale during a refetch.
                    // The header keeps full opacity so the tier controls and status stay legible.
                    isSwitchingTier && "[&>*:not(:first-child)]:opacity-40 [&>*:not(:first-child)]:transition-opacity [&>*:not(:first-child)]:duration-200"
                )}
            >

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
                                <span className="text-[11px] font-normal text-gray-500 tracking-[0.12em] uppercase mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                                    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                                        <Clock className="h-3 w-3" />
                                        Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                    </span>
                                    {isSwitchingTier && (
                                        <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-amber-500/20 bg-amber-500/[0.06] px-1.5 py-0.5 text-amber-300/90">
                                            <RefreshCw className="h-3 w-3 animate-spin" />
                                            Recomputing {COST_TIER_OPTIONS.find(option => option.value === costTier)?.label ?? costTier}
                                        </span>
                                    )}
                                    {rebalanceActive && (
                                        <button
                                            type="button"
                                            onClick={() => setShowRebalanceHistory(true)}
                                            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-sky-500/10 bg-sky-500/[0.04] px-1.5 py-0.5 text-sky-300/90 transition-colors hover:border-sky-500/25 hover:bg-sky-500/[0.1] hover:text-sky-200"
                                            title={`Dated accounting active. Latest event: ${latestRebalanceEvent?.label ?? 'snapshot'} (${latestRebalanceEvent?.effectiveDate ?? 'n/a'}).`}
                                        >
                                            <GitBranch className="h-3 w-3" />
                                            Dated book {rebalance?.eventCount ?? 0}
                                        </button>
                                    )}
                                </span>
                            </div>
                        </h1>
                    </div>

                    {/* Header Controls */}
                    <div className="flex flex-col sm:flex-row sm:flex-wrap xl:flex-nowrap items-stretch sm:items-center gap-3 text-sm w-full xl:w-auto">

                        {/* Exposure Pills */}
                        <div className="grid grid-cols-2 items-stretch gap-2 w-full sm:grid-cols-[minmax(150px,auto)_minmax(132px,1fr)_minmax(132px,1fr)] xl:w-auto">
                            <div className="col-span-2 sm:col-span-1">
                                <FxExposureWidget vitals={vitals} periodLabel={vitals?.periodLabel ?? "YTD"} />
                            </div>
                            <div
                                className="flex min-h-[68px] min-w-[132px] bg-gradient-to-br from-emerald-500/10 to-emerald-900/20 px-3 py-2 rounded-xl border border-emerald-500/20 backdrop-blur-md flex-col justify-center shadow-lg shadow-emerald-500/5 transition-all hover:scale-[1.02] hover:border-emerald-500/40"
                                title="Cost-aware current long exposure as a share of estimated net NAV, versus January starting exposure"
                            >
                                <p className="text-[9px] uppercase tracking-wider text-emerald-500/70 font-bold mb-0.5">Long Book</p>
                                <p className="font-mono text-emerald-400 font-black text-base leading-none">{formatPercent(currentLongExposure)}</p>
                                <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[9px] leading-none">
                                    <span className="text-emerald-300/55">Jan {formatPercent(januaryLongExposure)}</span>
                                    <span className={cn("font-mono font-bold", exposureDeltaClass(longExposureDelta))}>
                                        {formatBookDelta(longExposureDelta)}
                                    </span>
                                </p>
                            </div>
                            <div
                                className="flex min-h-[68px] min-w-[132px] bg-gradient-to-br from-rose-500/10 to-rose-900/20 px-3 py-2 rounded-xl border border-rose-500/20 backdrop-blur-md flex-col justify-center shadow-lg shadow-rose-500/5 transition-all hover:scale-[1.02] hover:border-rose-500/40"
                                title="Cost-aware current short exposure as a share of estimated net NAV, versus January starting exposure"
                            >
                                <p className="text-[9px] uppercase tracking-wider text-rose-500/70 font-bold mb-0.5">Short Book</p>
                                <p className="font-mono text-rose-400 font-black text-base leading-none">{formatPercent(currentShortExposure)}</p>
                                <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[9px] leading-none">
                                    <span className="text-rose-300/55">Jan {formatPercent(januaryShortExposure)}</span>
                                    <span className={cn("font-mono font-bold", exposureDeltaClass(shortExposureDelta))}>
                                        {formatBookDelta(shortExposureDelta)}
                                    </span>
                                </p>
                            </div>
                            <div
                                className="col-span-2 sm:col-span-3 rounded-xl border border-white/[0.07] bg-white/[0.035] px-3 py-2 text-[10px] shadow-lg shadow-black/10"
                                title="Net exposure is long minus short. Gross exposure is long plus short."
                            >
                                <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
                                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                                        <span className={cn(
                                            "font-bold uppercase tracking-[0.12em]",
                                            netExposureDelta > 0.005 ? "text-emerald-300" : netExposureDelta < -0.005 ? "text-sky-300" : "text-gray-400"
                                        )}>
                                            {netStanceLabel}
                                        </span>
                                        <span className="text-gray-500">/ {leverageStanceLabel}</span>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px]">
                                        <span className="text-gray-300">
                                            Net {formatBookPercent(currentNetExposure)}
                                            <span className="ml-1 text-gray-600">Jan {formatBookPercent(januaryNetExposure)}</span>
                                            <span className={cn("ml-1 font-bold", exposureDeltaClass(netExposureDelta))}>
                                                {formatBookDelta(netExposureDelta)}
                                            </span>
                                        </span>
                                        <span className="text-gray-300">
                                            Gross {formatBookPercent(currentGrossExposure)}
                                            <span className="ml-1 text-gray-600">Jan {formatBookPercent(januaryGrossExposure)}</span>
                                            <span className={cn("ml-1 font-bold", exposureDeltaClass(grossExposureDelta))}>
                                                {formatBookDelta(grossExposureDelta)}
                                            </span>
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>



                        {/* Cost Tier Toggle & Refresh Wrapper */}
                        <div className="flex w-full sm:w-auto items-center gap-3">

                            <div className="flex flex-1 sm:flex-none items-center rounded-lg border border-white/10 bg-white/[0.04] p-1 h-[40px] min-w-0">
                                <CircleDollarSign className="h-4 w-4 text-amber-400 mx-2 hidden sm:block" />
                                {COST_TIER_OPTIONS.map(option => {
                                    const active = costTier === option.value;
                                    const Icon = option.Icon;
                                    return (
                                        <button
                                            key={option.value}
                                            onClick={() => {
                                                if (!active) {
                                                    setIsSwitchingTier(true);
                                                    setCostTier(option.value);
                                                }
                                            }}
                                            aria-pressed={active}
                                            aria-label={option.label}
                                            className={cn(
                                                "group h-8 flex-1 sm:flex-none px-2 sm:px-2.5 rounded-md text-[10px] sm:text-[11px] font-bold uppercase tracking-[0.08em] transition-colors whitespace-nowrap",
                                                "inline-flex items-center justify-center gap-1.5",
                                                active
                                                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                                    : "text-gray-500 hover:text-gray-300 hover:bg-white/[0.04]"
                                            )}
                                            title={option.title}
                                        >
                                            <Icon className={cn(
                                                "h-3.5 w-3.5 shrink-0 transition-colors",
                                                active ? "text-amber-300" : "text-gray-500 group-hover:text-gray-300"
                                            )} />
                                            <span className="hidden sm:inline">{option.label}</span>
                                            <span className="sm:hidden">{option.short}</span>
                                        </button>
                                    );
                                })}
                            </div>

                            {/* Refresh Button */}
                            <button
                                onClick={() => {
                                    const staleSince = lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                                    setIsSwitchingTier(true);
                                    setRefreshError(null);
                                    fetchDashboardData(5, 1000, true, costTier, portfolioName).then(res => { // force=true
                                        if (res && !res.error) {
                                            setData(res);
                                            setLastUpdated(new Date());
                                        } else {
                                            // fetchDashboardData returns null once its retry loop is exhausted.
                                            setRefreshError(
                                                `${res?.error ?? 'Force refresh failed after 5 attempts.'} Still showing data from ${staleSince}.`
                                            );
                                        }
                                    }).finally(() => setIsSwitchingTier(false));
                                }}
                                className="bg-white/5 hover:bg-white/10 w-[40px] h-[40px] rounded-lg border border-white/10 transition-colors flex items-center justify-center shrink-0"
                                title="Force Refresh Data"
                            >
                                <RefreshCw className={cn("h-4 w-4 text-emerald-400", isSwitchingTier ? "animate-spin" : "")} />
                            </button>
                            <a
                                href="/dashboard/brain"
                                className="bg-white/5 hover:bg-white/10 h-[40px] rounded-lg border border-white/10 transition-colors inline-flex items-center justify-center gap-2 px-3 shrink-0 text-[11px] font-bold uppercase tracking-[0.08em] text-gray-300"
                                title="Open Investment Brain"
                            >
                                <BrainCircuit className="h-4 w-4 text-violet-300" />
                                <span className="hidden md:inline">Brain</span>
                            </a>
                        </div>
                    </div>
                </div>

                {refreshError && (
                    <div className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-4 py-3">
                        <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
                        <p className="flex-1 text-xs leading-5 text-amber-200/90">{refreshError}</p>
                        <button
                            type="button"
                            onClick={() => setRefreshError(null)}
                            className="shrink-0 rounded-md p-1 text-amber-300/70 transition-colors hover:bg-white/[0.06] hover:text-amber-200"
                            aria-label="Dismiss refresh warning"
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                    </div>
                )}

                {/* NEW: ExecutiveSummary (YTD Returns, Alpha, Benchmarks, Financing, Stress Tests) */}
                <ExecutiveSummary vitals={vitals} costTier={costTier} ytdHistory={ytdHistory} stressTests={stressTests} momentum={data.momentum} convexity={convexity} />

                {/* ROW 1.5: Returns Heatmap & Portfolio Contribution (Full Width) */}
                <ReturnsHeatmap periodicReturns={periodicReturns} activeRisks={activeRisks} periodLabel={vitals?.periodLabel ?? "YTD"} vitals={vitals} />

                <HistoricalDiagnostics data={analyticsHistory} performance={ytdHistory} periodLabel={vitals?.periodLabel ?? "YTD"} />

                {/* ROW 2: Convexity Analysis */}
                <ConvexityWidget convexity={convexity} />

                {/* ROW 3: World Map (Full Width, lazy-loaded — heaviest widget) */}
                <Suspense fallback={<WidgetSkeleton height="h-[450px]" />}>
                    <CountryMapWidget countryAllocation={countryAllocation} />
                </Suspense>

            </div>
            </div>

            <RebalanceHistoryModal
                rebalance={rebalance}
                open={showRebalanceHistory}
                onClose={() => setShowRebalanceHistory(false)}
            />
        </div>
    );
};
