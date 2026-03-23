import { cn } from '../../lib/utils';
import type { Vitals, LeverageStats } from '../../utils/finance';
import {
    TrendingUp, TrendingDown, Activity, Zap, Shield,
    BarChart3, ArrowUpRight, ArrowDownRight,
    Gauge, Flame, DollarSign
} from 'lucide-react';

interface ExecutiveSummaryProps {
    vitals: Vitals;
    leverage?: LeverageStats;
    costTier?: string;
}

// ─── Formatters ──────────────────────────────────────────────
const fmt = (val: number | undefined, decimals = 2) =>
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
export const ExecutiveSummary: React.FC<ExecutiveSummaryProps> = ({ vitals, leverage, costTier = 'retail' }) => {
    const ytdPositive = (vitals.ytdReturn ?? 0) >= 0;

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
                            <span className="text-[11px] text-gray-400 uppercase tracking-[0.15em] font-semibold">2026 YTD Return</span>
                        </div>

                        <div className="flex items-end gap-3">
                            <span className={cn(
                                "text-4xl sm:text-5xl font-black tracking-tighter leading-none",
                                ytdPositive ? "text-emerald-400" : "text-rose-400"
                            )} title="Net Return (After financing drag)">
                                {fmtSigned(vitals.ytdReturn)}
                            </span>
                            {vitals.ytdReturnGross !== undefined && (
                                <span className="text-[10px] text-gray-500 font-mono mb-1.5 whitespace-nowrap bg-white/5 px-2 py-0.5 rounded border border-white/5"
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
                            { label: '🇵🇱 PLN', value: vitals.ytdReturnPln },
                        ].map(b => (
                            <div key={b.label} className="flex flex-col items-center py-2.5 px-2">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">{b.label}</span>
                                <span className={cn("font-mono text-sm font-bold tracking-tight mt-0.5", returnColor(b.value))}>
                                    {fmtSigned(b.value)}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* ── RIGHT PANEL: 2x2 compact metrics ── */}
                <div className="md:col-span-7 lg:col-span-8 grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3">

                    {/* Alpha */}
                    <div className="rounded-xl border border-amber-500/20 bg-gradient-to-br from-amber-950/30 to-slate-950/90 p-4 flex flex-col justify-between">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Zap className="h-3.5 w-3.5 text-amber-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Alpha</span>
                        </div>
                        <span className={cn(
                            "text-2xl sm:text-3xl font-black tracking-tight",
                            (vitals.ytdAlphaRaw ?? 0) >= 0 ? "text-amber-400" : "text-rose-400"
                        )}>
                            {fmtSigned(vitals.ytdAlphaRaw)}
                        </span>
                        <div className="mt-2 pt-2 border-t border-white/[0.06]">
                            <StatRow label="Ann." value={fmtSigned(vitals.ytdAlpha)}
                                valueClassName={(vitals.ytdAlpha ?? 0) >= 0 ? "text-amber-400/70" : "text-rose-400/70"} />
                        </div>
                    </div>

                    {/* Beta / Market Conditions */}
                    <div className="rounded-xl border border-blue-500/20 bg-gradient-to-br from-blue-950/20 to-slate-950/90 p-4 flex flex-col justify-between">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Activity className="h-3.5 w-3.5 text-blue-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Beta</span>
                        </div>
                        <span className="text-2xl sm:text-3xl font-black tracking-tight text-white">
                            {fmtNum(vitals.ytdBeta)}
                        </span>
                        <div className="mt-2 pt-2 border-t border-white/[0.06]">
                            <div className="flex justify-between items-center">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Regime</span>
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

                    {/* YTD Sharpe */}
                    <div className="rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-950/20 to-slate-950/90 p-4 flex flex-col justify-between">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Gauge className="h-3.5 w-3.5 text-violet-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Sharpe</span>
                        </div>
                        <span className={cn(
                            "text-2xl sm:text-3xl font-black tracking-tight",
                            (vitals.ytdSharpe ?? 0) > 1 ? "text-emerald-400" : (vitals.ytdSharpe ?? 0) > 0.5 ? "text-white" : "text-gray-400"
                        )}>
                            {fmtNum(vitals.ytdSharpe)}
                        </span>
                        <div className="mt-2 pt-2 border-t border-white/[0.06]">
                            <StatRow label="SPY" value={fmtNum(vitals.benchmarkYtdSharpe)} valueClassName="text-gray-400" />
                        </div>
                    </div>

                    {/* Max Drawdown */}
                    <div className={cn(
                        "rounded-xl border p-4 flex flex-col justify-between bg-gradient-to-br",
                        (vitals.ytdMaxDrawdown ?? 0) < -0.1
                            ? "border-rose-500/30 from-rose-950/30 to-slate-950/90"
                            : "border-white/10 from-slate-900/50 to-slate-950/90"
                    )}>
                        <div className="flex items-center gap-1.5 mb-2">
                            <TrendingDown className="h-3.5 w-3.5 text-rose-400" />
                            <span className="text-[10px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Max DD</span>
                        </div>
                        <span className={cn(
                            "text-2xl sm:text-3xl font-black tracking-tight",
                            (vitals.ytdMaxDrawdown ?? 0) < -0.1 ? "text-rose-400"
                                : (vitals.ytdMaxDrawdown ?? 0) < -0.05 ? "text-amber-400" : "text-emerald-400"
                        )}>
                            {fmt(vitals.ytdMaxDrawdown)}
                        </span>
                        <div className="mt-2 pt-2 border-t border-white/[0.06]">
                            <StatRow label="SPY" value={fmt(vitals.benchmarkYtdMaxDrawdown)} valueClassName="text-gray-400" />
                        </div>
                    </div>
                </div>
            </div>

            {/* ═══════ ROW 2: L/S Contribution + Financing ═══════ */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

                {/* L/S Contribution */}
                <div className="rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl">
                    <div className="flex items-center gap-2 mb-3">
                        <BarChart3 className="h-4 w-4 text-blue-400" />
                        <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">L/S Contribution</span>
                    </div>
                    <div className="space-y-2">
                        <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
                            <div className="flex items-center gap-2">
                                <span className="flex items-center justify-center w-5 h-5 rounded bg-emerald-500/15">
                                    <ArrowUpRight className="h-3 w-3 text-emerald-400" />
                                </span>
                                <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider">Longs</span>
                            </div>
                            <span className={cn("font-mono text-lg font-black tracking-tight", returnColor(vitals.ytdLongsContrib))}>
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
                            <span className={cn("font-mono text-lg font-black tracking-tight", returnColor(vitals.ytdShortsContrib))}>
                                {fmtSigned(vitals.ytdShortsContrib)}
                            </span>
                        </div>
                        {/* Visual bar */}
                        <div className="flex items-center gap-1 mt-1">
                            <div className="flex-1 h-2 rounded-l-full bg-emerald-500/30 overflow-hidden">
                                <div className="h-full bg-emerald-500/60 rounded-l-full transition-all duration-700"
                                    style={{ width: `${Math.min(Math.abs((vitals.ytdLongsContrib ?? 0)) * 500, 100)}%` }} />
                            </div>
                            <div className="w-px h-3 bg-white/20" />
                            <div className="flex-1 h-2 rounded-r-full bg-rose-500/30 overflow-hidden flex justify-end">
                                <div className="h-full bg-rose-500/60 rounded-r-full transition-all duration-700"
                                    style={{ width: `${Math.min(Math.abs((vitals.ytdShortsContrib ?? 0)) * 500, 100)}%` }} />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Financing Impact */}
                <div className="rounded-xl border border-indigo-500/15 bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl">
                    <div className="flex items-center gap-2 mb-3">
                        <DollarSign className="h-4 w-4 text-indigo-400" />
                        <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">
                            Financing
                            <span className="ml-1.5 text-[9px] text-gray-600 normal-case tracking-normal">
                                ({costTier.charAt(0).toUpperCase() + costTier.slice(1)})
                            </span>
                        </span>
                    </div>
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
                            <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider"
                                title="Accumulated financing drag since Jan 1">YTD Drag</span>
                            <span className="font-mono text-lg font-black tracking-tight text-rose-400">
                                {vitals.ytdFinancingCost !== undefined ? fmt(-vitals.ytdFinancingCost) : '—'}
                            </span>
                        </div>
                        <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
                            <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider"
                                title="Annualized estimate of combined margin & borrow fees">Ann. Est</span>
                            <span className="font-mono text-lg font-black tracking-tight text-amber-400">
                                {vitals.annualFinancingCost !== undefined ? fmt(-vitals.annualFinancingCost) : '—'}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Leverage / Exposure */}
                <div className="rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl">
                    <div className="flex items-center gap-2 mb-3">
                        <Flame className="h-4 w-4 text-orange-400" />
                        <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Exposure</span>
                    </div>
                    {leverage ? (
                        <div className="space-y-1.5">
                            <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
                                <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider">Gross</span>
                                <span className="font-mono text-lg font-black tracking-tight text-indigo-400">
                                    {(leverage.Gross_Exp * 100).toFixed(0)}%
                                </span>
                            </div>
                            <div className="grid grid-cols-2 gap-1.5">
                                <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-2.5 py-2 border border-white/[0.05]">
                                    <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">Long</span>
                                    <span className="font-mono text-sm font-bold text-emerald-400">
                                        {(leverage.Long_Exp * 100).toFixed(0)}%
                                    </span>
                                </div>
                                <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-2.5 py-2 border border-white/[0.05]">
                                    <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">Short</span>
                                    <span className="font-mono text-sm font-bold text-rose-400">
                                        {(leverage.Short_Exp * 100).toFixed(0)}%
                                    </span>
                                </div>
                            </div>
                            <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2 border border-white/[0.05]">
                                <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider">Net</span>
                                <span className="font-mono text-sm font-bold text-gray-200">
                                    {(leverage.Net_Exp * 100).toFixed(0)}%
                                </span>
                            </div>
                        </div>
                    ) : (
                        <span className="text-gray-600 text-sm">No leverage data</span>
                    )}
                </div>
            </div>
        </div>
    );
};
