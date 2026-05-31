import React from 'react';
import { cn } from '../../lib/utils';
import type { Vitals, HistoryPoint, StressTest, MomentumMetrics, ConvexityMetrics } from '../../utils/finance';
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
    <div className="flex justify-between items-center py-1.5" title={tooltip}>
        <span className="text-[11px] text-gray-500 uppercase tracking-wider font-medium">{label}</span>
        <span className={cn("font-mono text-[13px] font-bold tracking-tight", valueClassName || "text-gray-200")}>
            {value}
        </span>
    </div>
);

// ─── Main Component ──────────────────────────────────────────
export const ExecutiveSummary: React.FC<ExecutiveSummaryProps> = React.memo(({ vitals, costTier = 'retail', ytdHistory, stressTests, momentum, convexity }) => {
    const ytdPositive = (vitals.ytdReturn ?? 0) >= 0;
    const periodLabel = vitals.periodLabel ?? "YTD";

    return (
        <div className="space-y-4">

            {/* ═══════ ROW 1: Hero Return + Key Metrics ═══════ */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-4">

                {/* ── HERO: YTD Return ── */}
                <div className={cn(
                    "md:col-span-5 lg:col-span-4 rounded-2xl overflow-hidden",
                    "border", ytdPositive ? "border-emerald-500/20" : "border-rose-500/20",
                    "bg-gradient-to-br",
                    ytdPositive ? "from-emerald-950/40 via-slate-900/90 to-slate-950" : "from-rose-950/40 via-slate-900/90 to-slate-950",
                    "shadow-2xl shadow-black/30"
                )}>
                    <div className="p-5 pb-3">
                        <div className="flex items-center gap-2 mb-3">
                            <div className={cn(
                                "flex items-center justify-center w-7 h-7 rounded-lg",
                                ytdPositive ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/15 text-rose-400"
                            )}>
                                {ytdPositive ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                            </div>
                            <span className="text-[11px] text-gray-400 uppercase tracking-[0.15em] font-semibold">{periodLabel} Return</span>
                        </div>

                        <div className="flex items-baseline gap-2.5">
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
                                    title="Gross Return (Before financing drag)">
                                    gross {fmtSigned(vitals.ytdReturnGross)}
                                </span>
                            )}
                        </div>
                    </div>

                    {/* Benchmark comparison strip */}
                    <div className="grid grid-cols-3 divide-x divide-white/[0.06] border-t border-white/[0.06] bg-white/[0.02]">
                        {[
                            { label: 'SPY', value: vitals.benchmarkYtd },
                            { label: 'MSCI', value: vitals.msciYtd },
                            { label: '🇵🇱 WIG20', value: vitals.wigYtd },
                        ].map(b => {
                            const portfolioRet = vitals.ytdReturn ?? 0;
                            const bVal = b.value ?? 0;
                            const delta = portfolioRet - bVal;
                            return (
                                <div key={b.label} className="flex flex-col items-center py-2.5 px-2 gap-0.5">
                                    <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">{b.label}</span>
                                    <span className={cn("font-mono text-sm font-bold tracking-tight", returnColor(b.value))}>
                                        {fmtSigned(b.value)}
                                    </span>
                                    <span className={cn(
                                        "text-[9px] font-mono font-semibold flex items-center gap-0.5",
                                        delta >= 0 ? "text-emerald-500/80" : "text-rose-500/80"
                                    )}>
                                        {delta >= 0 ? '▲' : '▼'} {Math.abs(delta * 100).toFixed(1)}pp
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* ── RIGHT PANEL: 2x2 compact metrics ── */}
                <div className="md:col-span-7 lg:col-span-8 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">

                    {/* Alpha */}
                    <div className="rounded-xl border border-amber-500/20 bg-gradient-to-br from-amber-950/30 to-slate-950/90 p-4 flex flex-col">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Zap className="h-3.5 w-3.5 text-amber-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Alpha</span>
                        </div>
                        <div className="h-[36px] flex items-end">
                            <span className={cn(
                                "text-2xl sm:text-3xl font-black tracking-tight leading-none",
                                (vitals.ytdAlphaRaw ?? 0) >= 0 ? "text-amber-400" : "text-rose-400"
                            )}>
                                {fmtSigned(vitals.ytdAlphaRaw)}
                            </span>
                        </div>
                        <div className="mt-auto pt-2 border-t border-white/[0.06]">
                            <StatRow label="Ann." value={fmtSigned(vitals.ytdAlpha)}
                                valueClassName={(vitals.ytdAlpha ?? 0) >= 0 ? "text-amber-400/70" : "text-rose-400/70"} />
                        </div>
                    </div>

                    {/* Beta */}
                    <div className="rounded-xl border border-blue-500/20 bg-gradient-to-br from-blue-950/20 to-slate-950/90 p-4 flex flex-col">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Activity className="h-3.5 w-3.5 text-blue-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Beta</span>
                        </div>
                        <div className="flex items-end justify-between gap-3 w-full h-[36px]">
                            <span className="text-2xl sm:text-3xl font-black tracking-tight text-white leading-none shrink-0">
                                {fmtNum(vitals.ytdBeta)}
                            </span>
                            {ytdHistory && ytdHistory.length > 0 && (
                                <div className="h-[36px] flex-1 opacity-80">
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
                                                                <p className="text-blue-400 font-mono font-bold">β: {data.beta?.toFixed(3)}</p>
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
                        <div className="mt-auto pt-2 border-t border-white/[0.06]">
                            <div className="flex justify-between items-center py-1.5">
                                <span className="text-[11px] text-gray-500 uppercase tracking-wider font-medium">Regime</span>
                                <span className={cn(
                                    "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider",
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
                    <div className="rounded-xl border border-cyan-500/20 bg-gradient-to-br from-cyan-950/20 to-slate-950/90 p-4 flex flex-col">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Activity className="h-3.5 w-3.5 text-cyan-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Correlation</span>
                        </div>
                        <div className="h-[36px] flex items-end">
                            <span className={cn(
                                "text-2xl sm:text-3xl font-black tracking-tight leading-none",
                                (vitals.ytdCorrelation ?? 0) > 0.7 ? "text-emerald-400" : (vitals.ytdCorrelation ?? 0) < 0 ? "text-rose-400" : "text-white"
                            )}>
                                {fmtNum(vitals.ytdCorrelation)}
                            </span>
                        </div>
                        <div className="mt-auto pt-2 border-t border-white/[0.06]">
                            <div className="flex justify-between items-center py-1.5">
                                <span className="text-[11px] text-gray-500 uppercase tracking-wider font-medium">vs SPY</span>
                                <span className={cn(
                                    "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider",
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
                    <div className="rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-950/20 to-slate-950/90 p-4 flex flex-col">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Gauge className="h-3.5 w-3.5 text-violet-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Sharpe</span>
                        </div>
                        <div className="h-[36px] flex items-end">
                            <span className={cn(
                                "text-2xl sm:text-3xl font-black tracking-tight leading-none",
                                (vitals.ytdSharpe ?? 0) > 1 ? "text-emerald-400" : (vitals.ytdSharpe ?? 0) > 0.5 ? "text-white" : "text-gray-400"
                            )}>
                                {fmtNum(vitals.ytdSharpe)}
                            </span>
                        </div>
                        <div className="mt-auto pt-2 border-t border-white/[0.06]">
                            <StatRow label="SPY" value={fmtNum(vitals.benchmarkYtdSharpe)} valueClassName="text-gray-400" />
                        </div>
                    </div>

                    {/* Max Drawdown */}
                    <div className={cn(
                        "rounded-xl border p-4 flex flex-col bg-gradient-to-br",
                        (vitals.ytdMaxDrawdown ?? 0) < -0.1
                            ? "border-rose-500/30 from-rose-950/30 to-slate-950/90"
                            : "border-white/10 from-slate-900/50 to-slate-950/90"
                    )}>
                        <div className="flex items-center gap-1.5 mb-2">
                            <TrendingDown className="h-3.5 w-3.5 text-rose-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Max DD</span>
                        </div>
                        <div className="h-[36px] flex items-end">
                            <span className={cn(
                                "text-2xl sm:text-3xl font-black tracking-tight leading-none",
                                (vitals.ytdMaxDrawdown ?? 0) < -0.1 ? "text-rose-400"
                                    : (vitals.ytdMaxDrawdown ?? 0) < -0.05 ? "text-amber-400" : "text-emerald-400"
                            )}>
                                {fmt(vitals.ytdMaxDrawdown)}
                            </span>
                        </div>
                        <div className="mt-auto pt-2 border-t border-white/[0.06]">
                            <StatRow label="SPY" value={fmt(vitals.benchmarkYtdMaxDrawdown)} valueClassName="text-gray-400" />
                        </div>
                    </div>

                    {/* Volatility — Portfolio vs SPY */}
                    <div className="rounded-xl border border-orange-500/20 bg-gradient-to-br from-orange-950/20 to-slate-950/90 p-4 flex flex-col">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Activity className="h-3.5 w-3.5 text-orange-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Volatility</span>
                        </div>
                        <div className="h-[36px] flex items-end">
                            <span className={cn(
                                "text-2xl sm:text-3xl font-black tracking-tight leading-none",
                                (vitals.ytdVol ?? 0) > (vitals.benchmarkYtdVol ?? 0) ? "text-orange-400" : "text-emerald-400"
                            )}>
                                {fmt(vitals.ytdVol)}
                            </span>
                        </div>
                        <div className="mt-auto pt-2 border-t border-white/[0.06] space-y-1.5">
                            <StatRow label="SPY" value={fmt(vitals.benchmarkYtdVol)} valueClassName="text-gray-400" />
                            {/* Ratio bar */}
                            {(() => {
                                const pVol = vitals.ytdVol ?? 0;
                                const bVol = vitals.benchmarkYtdVol ?? 1;
                                const ratio = bVol > 0 ? pVol / bVol : 1;
                                const isHigher = ratio > 1;
                                return (
                                    <div className="flex flex-col gap-1">
                                        <div className="flex items-center gap-1.5">
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
                                                {ratio.toFixed(2)}×
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
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">

                {/* ── L/S Contribution, Financing & Momentum — 4 cols ── */}
                <div className="lg:col-span-4 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <BarChart3 className="h-4 w-4 text-blue-400" />
                            <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">L/S · Financing · Momentum</span>
                        </div>
                        <span className="text-[9px] text-gray-500 uppercase tracking-widest bg-white/[0.03] px-2 py-0.5 rounded border border-white/[0.05]">
                            {costTier}
                        </span>
                    </div>

                    <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
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

                    <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
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
                        <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">{periodLabel} Drag</span>
                        <span className="font-mono text-sm font-black tracking-tight text-rose-400">
                            {vitals.ytdFinancingCost !== undefined ? fmt(-vitals.ytdFinancingCost) : '—'}
                        </span>
                    </div>
                    <div className="flex justify-between items-center -mt-1">
                        <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">Ann. Est</span>
                        <span className="font-mono text-sm font-black tracking-tight text-amber-400">
                            {vitals.annualFinancingCost !== undefined ? fmt(-vitals.annualFinancingCost) : '—'}
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
                <div className="lg:col-span-4 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl flex flex-col gap-2">
                    {/* Header */}
                    <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                            <Zap className="h-4 w-4 text-violet-400" />
                            <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Stress Tests</span>
                        </div>
                        <span
                            className="text-[9px] text-gray-600 bg-white/[0.03] border border-white/[0.06] px-2 py-0.5 rounded cursor-help"
                            title="Each scenario simulates a sudden SPY market move. The portfolio impact is estimated using a quadratic regression model fitted to YTD daily returns: Portfolio Return = α + β₁·(market move) + β₂·(market move)². This non-linear model accounts for long/short convexity. The linear baseline is simply β × market move."
                        >
                            ƒ(x) model ?
                        </span>
                    </div>

                    {stressTests?.map(st => {
                        const mktMove = st.marketMove ?? 0;
                        const diff = st.linearImpact != null ? st.impact - st.linearImpact : 0;
                        const hasBoth = st.linearImpact != null && Math.abs(diff) > 0.0001;
                        const convexBenefit = diff > 0;
                        const isCrash = mktMove < -0.07;
                        const isDown = mktMove < 0;

                        // Color by scenario direction
                        const scenarioColor = isDown
                            ? (isCrash ? 'border-rose-500/25 bg-rose-950/10' : 'border-rose-500/15 bg-rose-950/5')
                            : (Math.abs(mktMove) > 0.07 ? 'border-emerald-500/25 bg-emerald-950/10' : 'border-emerald-500/15 bg-emerald-950/5');

                        return (
                            <div key={st.scenario} className={cn("rounded-lg px-3 py-2.5 border", scenarioColor)}>

                                {/* Row 1: Scenario label + SPY pill */}
                                <div className="flex items-center justify-between gap-2 mb-2">
                                    <span className="text-[10px] text-gray-400 font-bold uppercase tracking-wider">
                                        {st.scenario.replace(/\(.*?\)/, '').trim()}
                                    </span>
                                    <span className={cn(
                                        "font-mono text-[10px] font-black px-1.5 py-0.5 rounded border whitespace-nowrap",
                                        isDown
                                            ? "text-rose-300 bg-rose-900/30 border-rose-500/30"
                                            : "text-emerald-300 bg-emerald-900/30 border-emerald-500/30"
                                    )}>
                                        SPY {mktMove > 0 ? '+' : ''}{(mktMove * 100).toFixed(0)}%
                                    </span>
                                </div>

                                {/* Row 2: Two numbers side-by-side */}
                                <div className="grid grid-cols-2 gap-2 items-end">
                                    {/* Quadratic model — dominant */}
                                    <div className="flex flex-col gap-0.5">
                                        <span className="text-[8px] text-gray-600 uppercase tracking-widest font-semibold">
                                            ƒ(x) model
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
                                    <div className="flex flex-col gap-0.5 border-l border-white/[0.06] pl-2">
                                        <span className="text-[8px] text-gray-600 uppercase tracking-widest font-semibold">
                                            β only
                                        </span>
                                        <div className="flex items-end gap-1.5">
                                            <span className={cn(
                                                "font-mono text-xl font-black tracking-tight leading-none",
                                                st.linearImpact != null
                                                    ? (st.linearImpact >= 0 ? "text-sky-400" : "text-orange-400")
                                                    : "text-gray-600"
                                            )}>
                                                {st.linearImpact != null ? fmtSigned(st.linearImpact) : '—'}
                                            </span>
                                            {hasBoth && (
                                                <span className={cn(
                                                    "font-mono text-[9px] font-bold px-1 py-0.5 rounded mb-0.5 leading-none",
                                                    convexBenefit
                                                        ? "text-emerald-400 bg-emerald-900/40"
                                                        : "text-rose-400 bg-rose-900/40"
                                                )}>
                                                    {convexBenefit ? '▲' : '▼'}{Math.abs(diff * 100).toFixed(1)}pp
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        );
                    })}

                    {/* Methodology footnote */}
                    <div className="mt-1 rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                        <p className="text-[9px] text-gray-600 leading-relaxed">
                            <span className="text-gray-500 font-semibold">How it works: </span>
                            Each scenario applies a sudden SPY move (−10%, −5%, +5%, +10%). Your estimated portfolio impact uses the{' '}
                            <span className="text-violet-400/80">quadratic model</span> fit to YTD daily data:{' '}
                            <span className="font-mono text-[8px] text-gray-500">P = α + β₁·x + β₂·x²</span>.
                            The <span className="text-gray-400">β only</span> line is the naive linear estimate (β × move).
                            A positive pp edge means your portfolio loses <em>less</em> in crashes or gains <em>more</em> in rallies than a pure-beta position.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
});
