import React from 'react';
import { cn } from '../../lib/utils';
import type { Vitals, HistoryPoint, StressTest, MomentumMetrics, ConvexityMetrics, BenchmarkSource } from '../../utils/finance';
import { ConvexityWidget } from './ConvexityWidget';
import { ResponsiveContainer, LineChart, Line, Tooltip } from 'recharts';
import {
    TrendingUp, TrendingDown, Activity, Zap, Shield,
    BarChart3, ArrowUpRight, ArrowDownRight,
    Gauge, Flame
} from 'lucide-react';

interface ExecutiveSummaryProps {
    vitals: Vitals;
    costTier?: string;
    ytdHistory?: HistoryPoint[];
    stressTests?: StressTest[];
    momentum?: MomentumMetrics | null;
    convexity?: ConvexityMetrics | null;
}

// A benchmark tile is a comparison, so it has to say what it is compared against:
// which series, and in which currency the return is measured.
const benchmarkTitle = (source: BenchmarkSource | undefined, fallback: string) => {
    if (!source) return fallback;
    const parts = [`${source.label} (${source.ticker}), shown in ${source.currency}`];
    if (source.localCurrency && source.localCurrency !== source.currency) {
        parts.push(`quoted in ${source.localCurrency}; the ${source.currency} figure is what holding it would have returned for this book, so the pp gap is arithmetic`);
    }
    if (source.note) parts.push(source.note);
    if (source.warning) parts.push(`⚠ ${source.warning}`);
    return parts.join(' — ');
};

/** The benchmark's return in its own currency, only when that differs from the tile's. */
const localReading = (source: BenchmarkSource | undefined, fallback?: number | null) => {
    if (!source?.localCurrency || source.localCurrency === source.currency) return null;
    const value = source.localReturn ?? fallback;
    return typeof value === 'number' ? value : null;
};

// ─── Formatters ──────────────────────────────────────────────
const fmt = (val: number | undefined, decimals = 2) =>
    typeof val === 'number' ? `${(val * 100).toFixed(decimals)}%` : 'N/A';

const fmtPct = (val: number | undefined, decimals = 1) =>
    typeof val === 'number' ? `${(val * 100).toFixed(decimals)}%` : 'N/A';

const fmtSigned = (val: number | undefined, decimals = 2) => {
    if (typeof val !== 'number') return 'N/A';
    const sign = val > 0 ? '+' : '';
    return `${sign}${(val * 100).toFixed(decimals)}%`;
};

const fmtSignedPp = (val: number | undefined, decimals = 1) => {
    if (typeof val !== 'number') return 'N/A';
    const sign = val > 0 ? '+' : '';
    return `${sign}${(val * 100).toFixed(decimals)}pp`;
};

const fmtNum = (val: number | undefined) =>
    typeof val === 'number' ? val.toFixed(2) : 'N/A';

// ─── Color helpers ───────────────────────────────────────────
const returnColor = (val: number | undefined) => {
    if (typeof val !== 'number') return 'text-gray-500';
    return val >= 0 ? 'text-emerald-400' : 'text-rose-400';
};

// ─── Mini stat row ───────────────────────────────────────────
const StatRow = ({ label, value, tooltip, valueClassName }: {
    label: string; value: string; tooltip?: string; valueClassName?: string;
}) => (
    <div className="flex min-w-0 items-center justify-between gap-2 py-1.5" title={tooltip}>
        <span className="min-w-0 truncate text-[11px] text-gray-500 uppercase tracking-wider font-medium">{label}</span>
        <span className={cn("shrink-0 whitespace-nowrap text-right font-mono text-[13px] font-bold tracking-tight tabular-nums", valueClassName || "text-gray-200")}>
            {value}
        </span>
    </div>
);

// ─── Main Component ──────────────────────────────────────────
export const ExecutiveSummary: React.FC<ExecutiveSummaryProps> = React.memo(({ vitals, costTier = 'retail', ytdHistory, stressTests, momentum, convexity }) => {
    const ytdPositive = (vitals.ytdReturn ?? 0) >= 0;
    const periodLabel = vitals.periodLabel ?? "YTD";

    return (
        <div className="space-y-5">

            {/* ═══════ ROW 1: Hero Return + Key Metrics ═══════ */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-4 xl:gap-5">

                {/* ── HERO: YTD Return ── */}
                <div className={cn(
                    "md:col-span-5 lg:col-span-4 rounded-2xl overflow-hidden flex flex-col min-h-[186px]",
                    "border", ytdPositive ? "border-emerald-500/20" : "border-rose-500/20",
                    "bg-gradient-to-br",
                    ytdPositive ? "from-emerald-950/40 via-slate-900/90 to-slate-950" : "from-rose-950/40 via-slate-900/90 to-slate-950",
                    "shadow-2xl shadow-black/30"
                )}>
                    <div className="p-4 sm:p-5 pb-3 flex-1 flex flex-col justify-center">
                        <div className="flex items-center gap-2 mb-3">
                            <div className={cn(
                                "flex items-center justify-center w-7 h-7 rounded-lg",
                                ytdPositive ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/15 text-rose-400"
                            )}>
                                {ytdPositive ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                            </div>
                            <span className="text-[11px] text-gray-400 uppercase tracking-[0.15em] font-semibold">{periodLabel} Net Return</span>
                            <span
                                className="ml-auto rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.11em] text-emerald-300"
                                title={vitals.performanceScope}
                            >
                                Realised NAV
                            </span>
                        </div>

                        <div className="flex flex-wrap items-end gap-2.5">
                            <span
                                className={cn(
                                    "text-4xl sm:text-5xl font-black tracking-tighter leading-none transition-all duration-500",
                                    ytdPositive ? "text-emerald-400" : "text-rose-400"
                                )}
                                style={{
                                    filter: ytdPositive
                                        ? 'drop-shadow(0 0 20px rgba(52,211,153,0.35))'
                                        : 'drop-shadow(0 0 20px rgba(248,113,133,0.35))'
                                }}
                                title="Net Return (After financing drag)"
                            >
                                {fmtSigned(vitals.ytdReturn)}
                            </span>
                            {vitals.ytdReturnGross !== undefined && (
                                <span className="text-[10px] text-gray-500 font-mono whitespace-nowrap bg-white/5 px-2 py-0.5 rounded border border-white/5"
                                    title={vitals.contributionScope || "Gross security return before financing drag"}>
                                    security gross {fmtSigned(vitals.ytdReturnGross)}
                                </span>
                            )}
                        </div>
                    </div>

                    {/* Benchmark comparison strip */}
                    <div className="mt-auto border-t border-white/[0.06] bg-white/[0.02]">
                    <div className="min-h-[68px] grid grid-cols-3 divide-x divide-white/[0.06]">
                        {[
                            { label: 'SPY', value: vitals.benchmarkYtd, local: null, localCurrency: null, title: 'SPDR S&P 500 ETF, total return in USD' },
                            { label: 'MSCI', value: vitals.msciYtd, local: localReading(vitals.msciBenchmark, vitals.msciYtdLocal), localCurrency: vitals.msciBenchmark?.localCurrency ?? null, title: benchmarkTitle(vitals.msciBenchmark, 'iShares MSCI World ETF, in USD') },
                            { label: `🇵🇱 ${vitals.wigBenchmark?.label ?? 'WIG20'}`, value: vitals.wigYtd, local: localReading(vitals.wigBenchmark, vitals.wigYtdLocal), localCurrency: vitals.wigBenchmark?.localCurrency ?? null, title: benchmarkTitle(vitals.wigBenchmark, 'Polish equity benchmark') },
                        ].map(b => {
                            const portfolioRet = vitals.ytdReturn ?? 0;
                            const bVal = b.value ?? 0;
                            const delta = portfolioRet - bVal;
                            return (
                                <div key={b.label} title={b.title} className="flex flex-col items-center justify-center py-2 px-2 gap-0.5 h-full">
                                    <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">{b.label}</span>
                                    <span className={cn("font-mono text-sm font-bold tracking-tight", returnColor(b.value))}>
                                        {fmtSigned(b.value)}
                                    </span>
                                    <span className={cn(
                                        "text-[9px] font-mono font-semibold flex items-center gap-0.5",
                                        delta >= 0 ? "text-emerald-500/80" : "text-rose-500/80"
                                    )}>
                                        {delta >= 0 ? '+' : '-'}{Math.abs(delta * 100).toFixed(1)}pp
                                    </span>
                                    {/* The benchmark's own currency, when it is not the one the
                                        comparison is done in. Both numbers are real; only one of
                                        them can be subtracted from a USD portfolio return. */}
                                    {b.local !== null && b.localCurrency && (
                                        <span className="text-[9px] font-mono text-gray-600" title={`The benchmark's own return, in ${b.localCurrency}`}>
                                            {b.localCurrency} {fmtSigned(b.local, 1)}
                                        </span>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                    {/* The Polish benchmark is the one nobody can guess from a three-letter
                        label: a total-return tracker quoted in PLN, which sits above the WIG20
                        price index the press prints. A hover tooltip cannot say so on a phone. */}
                    <p className="border-t border-white/[0.06] px-3 py-1.5 text-center text-[9px] leading-4 text-gray-600">
                        {vitals.wigBenchmark
                            ? `All three in ${vitals.wigBenchmark.currency} so the pp gaps compare. ${vitals.wigBenchmark.label} is a total-return tracker — its ${vitals.wigBenchmark.localCurrency ?? 'local'} reading is below it, and it runs above the WIG20 price index.`
                            : 'Benchmark returns in the portfolio base currency.'}
                    </p>
                    </div>
                </div>

                {/* ── RIGHT PANEL: 2x2 compact metrics ── */}
                <div className="md:col-span-7 lg:col-span-8 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 xl:gap-4">

                    {/* Alpha */}
                    <div className="rounded-xl border border-amber-500/20 bg-gradient-to-br from-amber-950/30 to-slate-950/90 p-3.5 sm:p-4 flex min-w-0 flex-col overflow-hidden min-h-[158px]">
                        <div className="flex items-start gap-1.5 mb-2 min-h-[30px]">
                            <Zap className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold leading-tight">CAPM Alpha</span>
                        </div>
                        <div className="flex-1 flex min-w-0 items-center">
                            <span className={cn(
                                "block w-full whitespace-nowrap text-[clamp(1.55rem,7vw,2rem)] font-black leading-none tracking-[-0.045em] tabular-nums lg:text-[clamp(1.4rem,1.75vw,1.85rem)]",
                                (vitals.ytdAlphaRaw ?? 0) >= 0 ? "text-amber-400" : "text-rose-400"
                            )}>
                                {fmtSigned(vitals.ytdAlphaRaw)}
                            </span>
                        </div>
                        <div className="mt-auto pt-3 border-t border-white/[0.06] h-[62px] flex min-w-0 flex-col justify-center">
                            <StatRow label="Ann. arith." value={fmtSigned(vitals.ytdAlpha)}
                                valueClassName={(vitals.ytdAlpha ?? 0) >= 0 ? "text-amber-400/70" : "text-rose-400/70"} />
                        </div>
                    </div>

                    {/* Beta */}
                    <div className="rounded-xl border border-blue-500/20 bg-gradient-to-br from-blue-950/20 to-slate-950/90 p-3.5 sm:p-4 flex min-w-0 flex-col overflow-hidden min-h-[158px]">
                        <div className="flex items-start gap-1.5 mb-2 min-h-[30px]">
                            <Activity className="h-3.5 w-3.5 shrink-0 text-blue-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold leading-tight">Beta</span>
                        </div>
                        <div className="flex-1 flex min-w-0 items-center justify-between gap-2 w-full">
                            <span className="block shrink-0 whitespace-nowrap text-[clamp(1.55rem,7vw,2rem)] font-black leading-none tracking-[-0.045em] text-white tabular-nums lg:text-[clamp(1.4rem,1.75vw,1.85rem)]">
                                {fmtNum(vitals.ytdBeta)}
                            </span>
                            {ytdHistory && ytdHistory.length > 0 && (
                                <div className="h-[34px] min-w-[42px] flex-1 opacity-80">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={ytdHistory}>
                                            <Tooltip
                                                cursor={{ stroke: 'rgba(255,255,255,0.1)', strokeWidth: 1 }}
                                                content={({ active, payload }) => {
                                                    if (active && payload && payload.length) {
                                                        const data = payload[0].payload;
                                                        return (
                                                            <div className="bg-slate-900 border border-slate-700/50 p-2 rounded-lg shadow-xl text-xs backdrop-blur-md">
                                                                <p className="text-gray-400 mb-0.5">{data.date}</p>
                                                                <p className="text-blue-400 font-mono font-bold">Beta: {data.beta?.toFixed(3)}</p>
                                                            </div>
                                                        );
                                                    }
                                                    return null;
                                                }}
                                            />
                                            <Line type="monotone" dataKey="beta" stroke="#60a5fa" strokeWidth={2} dot={false} isAnimationActive={false} />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            )}
                        </div>
                        <div className="mt-auto pt-3 border-t border-white/[0.06] h-[62px] flex min-w-0 flex-col justify-center">
                            <div className="flex min-w-0 flex-col items-start justify-center gap-1 py-1">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium leading-none">Regime</span>
                                <span className={cn(
                                    "inline-flex shrink-0 items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider whitespace-nowrap",
                                    vitals.ytdBeta > 1
                                        ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                        : "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                                )}>
                                    {vitals.ytdBeta > 1 ? <Zap className="w-2.5 h-2.5" /> : <Shield className="w-2.5 h-2.5" />}
                                    {vitals.ytdBeta > 1 ? "Aggr." : "Def."}
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* Correlation */}
                    <div className="rounded-xl border border-cyan-500/20 bg-gradient-to-br from-cyan-950/20 to-slate-950/90 p-3.5 sm:p-4 flex min-w-0 flex-col overflow-hidden min-h-[158px]">
                        <div className="flex items-start gap-1.5 mb-2 min-h-[30px]">
                            <Activity className="h-3.5 w-3.5 shrink-0 text-cyan-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold leading-tight">Correlation</span>
                        </div>
                        <div className="flex-1 flex min-w-0 items-center">
                            <span className={cn(
                                "block w-full whitespace-nowrap text-[clamp(1.55rem,7vw,2rem)] font-black leading-none tracking-[-0.045em] tabular-nums lg:text-[clamp(1.4rem,1.75vw,1.85rem)]",
                                (vitals.ytdCorrelation ?? 0) > 0.7 ? "text-emerald-400" : (vitals.ytdCorrelation ?? 0) < 0 ? "text-rose-400" : "text-white"
                            )}>
                                {fmtNum(vitals.ytdCorrelation)}
                            </span>
                        </div>
                        <div className="mt-auto pt-3 border-t border-white/[0.06] h-[62px] flex min-w-0 flex-col justify-center">
                            <div className="flex min-w-0 flex-col items-start justify-center gap-1 py-1">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium leading-none">vs SPY</span>
                                <span className={cn(
                                    "inline-flex shrink-0 items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider whitespace-nowrap",
                                    (vitals.ytdCorrelation ?? 0) > 0.7
                                        ? "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20"
                                        : (vitals.ytdCorrelation ?? 0) >= 0.3
                                            ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                                            : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                )}>
                                    {(vitals.ytdCorrelation ?? 0) > 0.7 ? "High" : (vitals.ytdCorrelation ?? 0) >= 0.3 ? "Moderate" : "Low"}
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* YTD Sharpe */}
                    <div className="rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-950/20 to-slate-950/90 p-3.5 sm:p-4 flex min-w-0 flex-col overflow-hidden min-h-[158px]">
                        <div className="flex items-start gap-1.5 mb-2 min-h-[30px]">
                            <Gauge className="h-3.5 w-3.5 shrink-0 text-violet-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold leading-tight">Sharpe</span>
                        </div>
                        <div className="flex-1 flex min-w-0 items-center">
                            <span className={cn(
                                "block w-full whitespace-nowrap text-[clamp(1.55rem,7vw,2rem)] font-black leading-none tracking-[-0.045em] tabular-nums lg:text-[clamp(1.4rem,1.75vw,1.85rem)]",
                                (vitals.ytdSharpe ?? 0) > 1 ? "text-emerald-400" : (vitals.ytdSharpe ?? 0) > 0.5 ? "text-white" : "text-gray-400"
                            )}>
                                {fmtNum(vitals.ytdSharpe)}
                            </span>
                        </div>
                        <div className="mt-auto pt-3 border-t border-white/[0.06] h-[62px] flex min-w-0 flex-col justify-center">
                            <StatRow label="SPY" value={fmtNum(vitals.benchmarkYtdSharpe)} valueClassName="text-gray-400" />
                        </div>
                    </div>

                    {/* Max Drawdown */}
                    <div className={cn(
                        "rounded-xl border p-3.5 sm:p-4 flex min-w-0 flex-col overflow-hidden bg-gradient-to-br min-h-[158px]",
                        (vitals.ytdMaxDrawdown ?? 0) < -0.1
                            ? "border-rose-500/30 from-rose-950/30 to-slate-950/90"
                            : "border-white/10 from-slate-900/50 to-slate-950/90"
                    )}>
                        <div className="flex items-start gap-1.5 mb-2 min-h-[30px]">
                            <TrendingDown className="h-3.5 w-3.5 shrink-0 text-rose-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold leading-tight">{periodLabel} Drawdown</span>
                        </div>
                        <div className="flex-1 flex min-w-0 items-center">
                            <span className={cn(
                                "block w-full whitespace-nowrap text-[clamp(1.55rem,7vw,2rem)] font-black leading-none tracking-[-0.045em] tabular-nums lg:text-[clamp(1.4rem,1.75vw,1.85rem)]",
                                (vitals.ytdMaxDrawdown ?? 0) < -0.1 ? "text-rose-400"
                                    : (vitals.ytdMaxDrawdown ?? 0) < -0.05 ? "text-amber-400" : "text-emerald-400"
                            )}>
                                {fmt(vitals.ytdMaxDrawdown)}
                            </span>
                        </div>
                        <div className="mt-auto pt-3 border-t border-white/[0.06] h-[62px] flex min-w-0 flex-col justify-center">
                            <StatRow label="SPY" value={fmt(vitals.benchmarkYtdMaxDrawdown)} valueClassName="text-gray-400" />
                        </div>
                    </div>

                    {/* Volatility — Portfolio vs SPY */}
                    <div className="rounded-xl border border-orange-500/20 bg-gradient-to-br from-orange-950/20 to-slate-950/90 p-3.5 sm:p-4 flex min-w-0 flex-col overflow-hidden min-h-[158px]">
                        <div className="flex items-start gap-1.5 mb-2 min-h-[30px]">
                            <Activity className="h-3.5 w-3.5 shrink-0 text-orange-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold leading-tight">Volatility</span>
                        </div>
                        <div className="flex-1 flex min-w-0 items-center">
                            <span className={cn(
                                "block w-full whitespace-nowrap text-[clamp(1.55rem,7vw,2rem)] font-black leading-none tracking-[-0.045em] tabular-nums lg:text-[clamp(1.4rem,1.75vw,1.85rem)]",
                                (vitals.ytdVol ?? 0) > (vitals.benchmarkYtdVol ?? 0) ? "text-orange-400" : "text-emerald-400"
                            )}>
                                {fmt(vitals.ytdVol)}
                            </span>
                        </div>
                        <div className="mt-auto pt-3 border-t border-white/[0.06] h-[62px] flex min-w-0 flex-col justify-center space-y-1">
                            <StatRow label="SPY" value={fmt(vitals.benchmarkYtdVol)} valueClassName="text-gray-400" />
                            {/* Ratio bar */}
                            {(() => {
                                const pVol = vitals.ytdVol ?? 0;
                                const bVol = vitals.benchmarkYtdVol ?? 1;
                                const ratio = bVol > 0 ? pVol / bVol : 1;
                                const isHigher = ratio > 1;
                                return (
                                    <div className="flex min-w-0 flex-col gap-1">
                                        <div className="flex min-w-0 items-center gap-1.5">
                                            <div className="flex-1 h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                                                <div
                                                    className={cn(
                                                        "h-full rounded-full transition-all duration-700",
                                                        isHigher ? "bg-orange-500/60" : "bg-emerald-500/60"
                                                    )}
                                                    style={{ width: `${Math.min(ratio * 50, 100)}%` }}
                                                />
                                            </div>
                                            <span className={cn(
                                                "text-[9px] font-mono font-bold whitespace-nowrap",
                                                isHigher ? "text-orange-400" : "text-emerald-400"
                                            )}>
                                                {ratio.toFixed(2)}x
                                            </span>
                                        </div>
                                    </div>
                                );
                            })()}
                        </div>
                    </div>
                </div>
            </div>

            {/* ═══════ ROW 2: L/S+Momentum | Convexity | Stress Tests ═══════ */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 xl:gap-5">

                {/* ── L/S Contribution, Financing & Momentum — 4 cols ── */}
                <div className="lg:col-span-4 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-3.5 sm:p-4 backdrop-blur-xl flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <BarChart3 className="h-4 w-4 text-blue-400" />
                            <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Long / Short + Momentum</span>
                        </div>
                        <span className="text-[9px] text-gray-500 uppercase tracking-widest bg-white/[0.03] px-2 py-0.5 rounded border border-white/[0.05]">
                            {costTier}
                        </span>
                    </div>

                    <div className="flex min-h-[46px] items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
                        <div className="flex items-center gap-2">
                            <span className="flex items-center justify-center w-5 h-5 rounded bg-emerald-500/15">
                                <ArrowUpRight className="h-3 w-3 text-emerald-400" />
                            </span>
                            <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider">Longs</span>
                        </div>
                        <span className={cn("font-mono text-base font-black tracking-tight", returnColor(vitals.ytdLongsContrib))}>
                            {fmtSigned(vitals.ytdLongsContrib)}
                        </span>
                    </div>

                    <div className="flex min-h-[46px] items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
                        <div className="flex items-center gap-2">
                            <span className="flex items-center justify-center w-5 h-5 rounded bg-rose-500/15">
                                <ArrowDownRight className="h-3 w-3 text-rose-400" />
                            </span>
                            <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider">Shorts</span>
                        </div>
                        <span className={cn("font-mono text-base font-black tracking-tight", returnColor(vitals.ytdShortsContrib))}>
                            {fmtSigned(vitals.ytdShortsContrib)}
                        </span>
                    </div>

                    {/* Progress bar */}
                    <div className="flex items-center gap-1 px-1">
                        <div className="flex-1 h-1.5 rounded-l bg-emerald-500/20 overflow-hidden">
                            <div className="h-full bg-emerald-500/60 transition-all duration-700"
                                style={{ width: `${Math.min(Math.abs((vitals.ytdLongsContrib ?? 0)) * 500, 100)}%` }} />
                        </div>
                        <div className="w-px h-2 bg-white/20" />
                        <div className="flex-1 h-1.5 rounded-r bg-rose-500/20 overflow-hidden flex justify-end">
                            <div className="h-full bg-rose-500/60 transition-all duration-700"
                                style={{ width: `${Math.min(Math.abs((vitals.ytdShortsContrib ?? 0)) * 500, 100)}%` }} />
                        </div>
                    </div>

                    <div className="flex justify-between items-center">
                        <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider" title={vitals.financingScope}>Estimated Carry Impact</span>
                        <span className="font-mono text-sm font-black tracking-tight text-rose-400">
                            {vitals.ytdFinancingCost !== undefined ? fmt(-vitals.ytdFinancingCost) : 'N/A'}
                        </span>
                    </div>
                    <div className="flex justify-between items-center -mt-1">
                        <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">Target Annual Carry</span>
                        <span className="font-mono text-sm font-black tracking-tight text-amber-400">
                            {vitals.annualFinancingCost !== undefined ? fmt(-vitals.annualFinancingCost) : 'N/A'}
                        </span>
                    </div>

                    {/* Momentum: Relative Strength */}
                    <div className="border-t border-white/[0.05] pt-2">
                        <div className="flex items-center gap-2 mb-2">
                            <Flame className="h-3.5 w-3.5 text-orange-400" />
                            <span className="text-[10px] text-gray-500 uppercase tracking-[0.12em] font-semibold">1M vs Benchmark</span>
                        </div>
                        <div className="flex flex-col gap-1">
                            {momentum?.top_rs?.slice(0, 3).map((rs, i) => (
                                <div key={`top-${i}`} className="flex justify-between items-center py-0.5">
                                    <div className="flex items-center gap-1.5">
                                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                                        <span className="text-[11px] text-gray-200 font-mono font-semibold">{rs.ticker.split('.')[0]}</span>
                                    </div>
                                    <span className="text-[11px] text-emerald-400 font-mono font-bold">+{fmtPct(rs.rs)}</span>
                                </div>
                            ))}
                            <div className="border-t border-white/[0.04] my-0.5" />
                            {momentum?.bot_rs?.slice(0, 3).map((rs, i) => (
                                <div key={`bot-${i}`} className="flex justify-between items-center py-0.5">
                                    <div className="flex items-center gap-1.5">
                                        <span className="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0" />
                                        <span className="text-[11px] text-gray-500 font-mono font-semibold">{rs.ticker.split('.')[0]}</span>
                                    </div>
                                    <span className="text-[11px] text-rose-400 font-mono font-bold">{fmtPct(rs.rs)}</span>
                                </div>
                            ))}
                            {(!momentum?.top_rs || momentum.top_rs.length === 0) && (
                                <span className="text-xs text-gray-600 italic mt-1">No data</span>
                            )}
                        </div>
                    </div>
                </div>

                {/* ── Convexity Profile — 4 cols ── */}
                <div className="lg:col-span-4">
                    <ConvexityWidget convexity={convexity} compact />
                </div>

                {/* ── Stress Tests — 4 cols ── */}
                <div className="lg:col-span-4 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl flex flex-col gap-3">
                    {/* Header */}
                    <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2">
                            <Zap className="h-4 w-4 text-violet-400" />
                            <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Stress Tests</span>
                        </div>
                        <span
                            className="text-[9px] text-gray-500 bg-white/[0.03] border border-white/[0.06] px-2 py-0.5 rounded cursor-help whitespace-nowrap"
                            title="Headline stress removes the fitted intercept/alpha, then compounds the curve response. Recent alpha is shown separately as context."
                        >
                            Ex-alpha stress
                        </span>
                    </div>

                    {/* The YTD beta failing does not stop these scenarios rendering: they
                        fall back to a replay of today's book over the full history. That is
                        a different book from the Beta tile above, so it is stated rather
                        than left to look like the same measure. */}
                    {stressTests?.some(st => st.betaSource === 'static_current_book') && (
                        <div
                            className="mb-2 rounded border border-amber-500/20 bg-amber-500/[0.06] px-2 py-1.5 text-[9px] leading-4 text-amber-300/90"
                            title="This year's realised beta was unavailable, so these scenarios use a static replay of the current book over the full price history. It is an estimate from a different book than the Beta tile above."
                        >
                            Estimated from the current book over full history — this year's realised beta was unavailable.
                        </div>
                    )}

                    {stressTests?.map(st => {
                        const mktMove = st.marketMove ?? 0;
                        const shapeEffect = st.shapeEffect ?? (st.linearImpact != null ? st.impact - st.linearImpact : 0);
                        const alphaEffect = st.alphaEffect ?? (st.fittedImpact != null ? st.fittedImpact - st.impact : 0);
                        const hasShapeEffect = st.linearImpact != null && Math.abs(shapeEffect) > 0.0001;
                        const hasFittedImpact = st.fittedImpact != null && Math.abs(st.fittedImpact - st.impact) > 0.0001;
                        const shapeHelps = shapeEffect > 0;
                        const alphaHelps = alphaEffect > 0;
                        const isCrash = mktMove < -0.07;
                        const isDown = mktMove < 0;

                        // Color by scenario direction
                        const scenarioColor = isDown
                            ? (isCrash ? 'border-rose-500/25 bg-rose-950/10' : 'border-rose-500/15 bg-rose-950/5')
                            : (Math.abs(mktMove) > 0.07 ? 'border-emerald-500/25 bg-emerald-950/10' : 'border-emerald-500/15 bg-emerald-950/5');

                        return (
                            <div key={st.scenario} className={cn("rounded-xl px-3.5 py-3 border", scenarioColor)}>

                                {/* Row 1: Scenario label + SPY pill */}
                                <div className="flex items-center justify-between gap-2 mb-3">
                                    <span className="text-[10px] text-gray-400 font-bold uppercase tracking-wider">
                                        {st.scenario.replace(/\(.*?\)/, '').trim()}
                                    </span>
                                    <div className="flex items-center gap-1.5 shrink-0">
                                        {st.stressDays && (
                                            <span className="font-mono text-[9px] font-bold px-1.5 py-0.5 rounded border border-white/[0.08] bg-white/[0.03] text-gray-500 whitespace-nowrap">
                                                {st.stressDays}d
                                            </span>
                                        )}
                                        <span className={cn(
                                            "font-mono text-[10px] font-black px-1.5 py-0.5 rounded border whitespace-nowrap",
                                            isDown
                                                ? "text-rose-300 bg-rose-900/30 border-rose-500/30"
                                                : "text-emerald-300 bg-emerald-900/30 border-emerald-500/30"
                                        )}>
                                            SPY {mktMove > 0 ? '+' : ''}{(mktMove * 100).toFixed(0)}%
                                        </span>
                                    </div>
                                </div>

                                {/* Row 2: Two numbers side-by-side */}
                                <div className="grid grid-cols-2 gap-3 items-end">
                                    {/* Quadratic model — dominant */}
                                    <div className="flex flex-col gap-0.5">
                                        <span className="text-[8px] text-gray-600 uppercase tracking-widest font-semibold">
                                            Ex-alpha
                                        </span>
                                        <span
                                            className={cn(
                                                "font-mono text-xl font-black tracking-tight leading-none",
                                                st.impact >= 0 ? "text-emerald-400" : "text-rose-400"
                                            )}
                                            style={{
                                                filter: st.impact >= 0
                                                    ? 'drop-shadow(0 0 8px rgba(52,211,153,0.25))'
                                                    : 'drop-shadow(0 0 8px rgba(248,113,133,0.25))'
                                            }}
                                        >
                                            {fmtSigned(st.impact)}
                                        </span>
                                    </div>

                                    {/* Beta-only — secondary */}
                                    <div className="flex flex-col gap-0.5 border-l border-white/[0.06] pl-3">
                                        <span className="text-[8px] text-gray-600 uppercase tracking-widest font-semibold">
                                            Beta only
                                        </span>
                                        <div className="flex flex-wrap items-end gap-1.5">
                                            <span className={cn(
                                                "font-mono text-xl font-black tracking-tight leading-none",
                                                st.linearImpact != null
                                                    ? (st.linearImpact >= 0 ? "text-sky-400" : "text-orange-400")
                                                    : "text-gray-600"
                                            )}>
                                                {st.linearImpact != null ? fmtSigned(st.linearImpact) : 'N/A'}
                                            </span>
                                            {hasShapeEffect && (
                                                <span className={cn(
                                                    "font-mono text-[9px] font-bold px-1 py-0.5 rounded mb-0.5 leading-none",
                                                    shapeHelps
                                                        ? "text-emerald-400 bg-emerald-900/40"
                                                        : "text-rose-400 bg-rose-900/40"
                                                )}>
                                                    Shape {fmtSignedPp(shapeEffect)}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {hasFittedImpact && (
                                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/[0.05] bg-white/[0.025] px-2.5 py-2">
                                        <span className="text-[8px] text-gray-600 uppercase tracking-widest font-semibold">
                                            Recent alpha
                                        </span>
                                        <div className="flex flex-wrap items-center justify-end gap-1.5">
                                            <span className={cn(
                                                "font-mono text-[10px] font-black tracking-tight",
                                                (st.fittedImpact ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                                            )}>
                                                {fmtSigned(st.fittedImpact)}
                                            </span>
                                            {Math.abs(alphaEffect) > 0.0001 && (
                                                <span className={cn(
                                                    "font-mono text-[9px] font-bold px-1 py-0.5 rounded leading-none",
                                                    alphaHelps
                                                        ? "text-emerald-400 bg-emerald-900/30"
                                                        : "text-rose-400 bg-rose-900/30"
                                                )}>
                                                    Alpha {fmtSignedPp(alphaEffect)}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}

                    {/* Methodology footnote */}
                    <div className="mt-1 rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2.5">
                        <p className="text-[10px] text-gray-600 leading-relaxed">
                            <span className="text-gray-500 font-semibold">How it works: </span>
                            Headline stress removes the fitted intercept/alpha and compounds the curve response.
                            Beta-only is the market-beta baseline; recent alpha is shown separately as context.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
});
