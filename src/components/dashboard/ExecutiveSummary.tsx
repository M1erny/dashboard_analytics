
import React from 'react';
import { cn } from '../../lib/utils';
import type { Vitals, LeverageStats } from '../../utils/finance';
import { TrendingUp, TrendingDown, Activity, Zap, Shield, BarChart3, PieChart } from 'lucide-react';

interface ExecutiveSummaryProps {
    vitals: Vitals;
    leverage?: LeverageStats;
    costTier?: string;
}

export const ExecutiveSummary: React.FC<ExecutiveSummaryProps> = ({ vitals, leverage, costTier = 'retail' }) => {
    const formatPercent = (val: number | undefined) => typeof val === 'number' ? `${(val * 100).toFixed(2)}%` : 'N/A';
    const formatNumber = (val: number | undefined) => typeof val === 'number' ? val.toFixed(2) : 'N/A';

    const MetricCard = ({
        title,
        icon: Icon,
        children,
        gradient = 'from-slate-800/50 to-slate-900/50',
        accentColor = 'border-white/10'
    }: {
        title: string;
        icon: React.ElementType;
        children: React.ReactNode;
        gradient?: string;
        accentColor?: string;
    }) => (
        <div className={cn(
            "relative overflow-hidden rounded-xl p-5 flex flex-col",
            "bg-gradient-to-br", gradient,
            "border", accentColor,
            "backdrop-blur-xl shadow-lg",
            "transition-all duration-300 hover:shadow-xl hover:scale-[1.02]",
            "group"
        )}>
            {/* Subtle glow effect */}
            <div className="absolute inset-0 bg-gradient-to-br from-white/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />

            {/* Fixed height title area ensures every card's content starts at EXACTLY the same Y position */}
            <div className="flex items-start gap-2 h-9 mb-1">
                <Icon className="h-4 w-4 text-gray-400 shrink-0 mt-0.5" />
                <span className="text-[11px] text-gray-400 uppercase tracking-wider font-bold leading-tight line-clamp-2">{title}</span>
            </div>
            
            <div>
                {children}
            </div>
        </div>
    );

    return (
        <div className="mb-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-4 gap-5">

            {/* Market Conditions */}
            <MetricCard
                title="Market Conditions"
                icon={Activity}
                gradient="from-slate-800/60 to-slate-900/80"
                accentColor="border-blue-500/20"
            >
                <div className="flex flex-col gap-3">
                    <div className="flex items-baseline gap-2">
                        <span className="font-mono text-3xl font-black text-white tracking-tight">{formatNumber(vitals.ytdBeta)}</span>
                    </div>
                    
                    <div className="flex justify-between items-center bg-white/5 rounded-lg px-3 py-2 border border-white/5 mt-1">
                        <span className="text-xs uppercase tracking-wider text-gray-400 font-semibold">Regime</span>
                        <span className={cn(
                            "font-mono text-[11px] font-bold px-2 py-1 rounded inline-flex items-center gap-1.5 uppercase tracking-wider",
                            vitals.ytdBeta > 1
                                ? "bg-amber-500/10 text-amber-500 border border-amber-500/20 shadow-lg shadow-amber-500/10"
                                : "bg-blue-500/10 text-blue-500 border border-blue-500/20 shadow-lg shadow-blue-500/10"
                        )}>
                            {vitals.ytdBeta > 1 ? <Zap className="w-3 h-3" /> : <Shield className="w-3 h-3" />}
                            {vitals.ytdBeta > 1 ? "Aggressive" : "Defensive"}
                        </span>
                    </div>
                </div>
            </MetricCard>

            {/* YTD Return */}
            <MetricCard
                title="2026 YTD Return"
                icon={vitals.ytdReturn >= 0 ? TrendingUp : TrendingDown}
                gradient={vitals.ytdReturn >= 0 ? "from-emerald-900/30 to-slate-900/80" : "from-rose-900/30 to-slate-900/80"}
                accentColor={vitals.ytdReturn >= 0 ? "border-emerald-500/30" : "border-rose-500/30"}
            >
                <div className="space-y-2">
                    <div className="flex items-baseline gap-2">
                        <span className={cn(
                            "text-3xl font-black tracking-tight",
                            vitals.ytdReturn >= 0 ? "text-emerald-400" : "text-rose-400"
                        )} title="Net Return (After financing drag)">
                            {vitals.ytdReturn > 0 ? "+" : ""}{formatPercent(vitals.ytdReturn)}
                        </span>
                        {vitals.ytdReturnGross !== undefined && (
                            <span className="text-[10px] text-gray-400 font-mono bg-white/5 px-1.5 py-0.5 rounded border border-white/5" title="Gross Return (Before financing drag)">
                                Gross: {formatPercent(vitals.ytdReturnGross)}
                            </span>
                        )}
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs mt-3">
                        <div className="flex-1 min-w-[70px] flex justify-between items-center bg-white/5 rounded-lg px-2.5 py-1.5 border border-white/5">
                            <span className="text-gray-400 font-semibold tracking-wider uppercase text-[10px]">SPY</span>
                            <span className="text-white font-mono font-bold text-sm tracking-tight">{formatPercent(vitals.benchmarkYtd)}</span>
                        </div>
                        <div className="flex-1 min-w-[70px] flex justify-between items-center bg-white/5 rounded-lg px-2.5 py-1.5 border border-white/5">
                            <span className="text-gray-400 font-semibold tracking-wider uppercase text-[10px]">MSCI</span>
                            <span className="text-white font-mono font-bold text-sm tracking-tight">{formatPercent(vitals.msciYtd)}</span>
                        </div>
                    </div>
                </div>
            </MetricCard>

            {/* L/S Contribution */}
            <MetricCard
                title="L/S Contribution"
                icon={BarChart3}
                gradient="from-slate-800/40 to-slate-900/80"
                accentColor="border-blue-500/20"
            >
                <div className="flex flex-col gap-3">
                    <div className="flex justify-between items-center bg-white/5 rounded-lg px-3 py-2 border border-white/5">
                        <span className="text-[11px] uppercase tracking-wider text-gray-400 font-bold flex items-center gap-1.5">
                            <TrendingUp className="w-3 h-3 text-blue-400" /> Longs
                        </span>
                        <span className={cn(
                            "font-mono text-lg font-black tracking-tight",
                            vitals.ytdLongsContrib >= 0 ? "text-emerald-400" : "text-rose-400"
                        )}>
                            {vitals.ytdLongsContrib > 0 ? "+" : ""}{formatPercent(vitals.ytdLongsContrib)}
                        </span>
                    </div>
                    
                    <div className="flex justify-between items-center bg-white/5 rounded-lg px-3 py-2 border border-white/5 mt-0.5">
                        <span className="text-[11px] uppercase tracking-wider text-gray-400 font-bold flex items-center gap-1.5">
                            <TrendingDown className="w-3 h-3 text-purple-400" /> Shorts
                        </span>
                        <span className={cn(
                            "font-mono text-lg font-black tracking-tight",
                            vitals.ytdShortsContrib >= 0 ? "text-emerald-400" : "text-rose-400"
                        )}>
                            {vitals.ytdShortsContrib > 0 ? "+" : ""}{formatPercent(vitals.ytdShortsContrib)}
                        </span>
                    </div>
                </div>
            </MetricCard>

            {/* PLN Return */}
            <MetricCard
                title="🇵🇱 YTD in PLN"
                icon={BarChart3}
                gradient={vitals.ytdReturnPln >= 0 ? "from-emerald-900/20 to-slate-900/80" : "from-rose-900/20 to-slate-900/80"}
                accentColor={vitals.ytdReturnPln >= 0 ? "border-emerald-500/20" : "border-rose-500/20"}
            >
                <div className="space-y-2">
                    <span className={cn(
                        "text-3xl font-black tracking-tight block",
                        vitals.ytdReturnPln >= 0 ? "text-emerald-400" : "text-rose-400"
                    )}>
                        {vitals.ytdReturnPln > 0 ? "+" : ""}{formatPercent(vitals.ytdReturnPln)}
                    </span>

                </div>
            </MetricCard>

            {/* Alpha */}
            <MetricCard
                title="Alpha"
                icon={Zap}
                gradient="from-amber-900/30 to-slate-900/80"
                accentColor="border-amber-500/40"
            >
                <div className="space-y-3">
                    {/* Raw Alpha (main) */}
                    <div className="flex items-baseline gap-2">
                        <span className={cn(
                            "text-3xl font-black tracking-tight",
                            vitals.ytdAlphaRaw >= 0 ? "text-amber-400" : "text-rose-400"
                        )}>
                            {vitals.ytdAlphaRaw > 0 ? "+" : ""}{formatPercent(vitals.ytdAlphaRaw)}
                        </span>

                    </div>
                    {/* Annualized Alpha */}
                    <div className="flex items-center gap-2 text-xs">
                        <span className="text-gray-500">Annualized:</span>
                        <span className={cn(
                            "font-mono font-bold px-2 py-0.5 rounded",
                            vitals.ytdAlpha >= 0 ? "text-amber-400 bg-amber-500/10" : "text-rose-400 bg-rose-500/10"
                        )}>
                            {vitals.ytdAlpha > 0 ? "+" : ""}{formatPercent(vitals.ytdAlpha)}
                        </span>
                    </div>
                </div>
            </MetricCard>

            {/* Risk Efficiency */}
            <MetricCard
                title="YTD Sharpe Ratio"
                icon={Shield}
                gradient="from-violet-900/20 to-slate-900/80"
                accentColor="border-violet-500/20"
            >
                <div className="space-y-2">
                    <div className="flex items-baseline gap-2">
                        <span className={cn(
                            "text-3xl font-black tracking-tight",
                            vitals.ytdSharpe > 1 ? "text-emerald-400" : vitals.ytdSharpe > 0.5 ? "text-white" : "text-gray-400"
                        )}>
                            {formatNumber(vitals.ytdSharpe)}
                        </span>
                        <span className="text-xs text-gray-500 bg-white/5 px-2 py-0.5 rounded">
                            SPY: {formatNumber(vitals.benchmarkYtdSharpe)}
                        </span>
                    </div>
                </div>
            </MetricCard>

            {/* YTD Max Drawdown */}
            <MetricCard
                title="YTD Max Drawdown"
                icon={TrendingDown}
                gradient={vitals.ytdMaxDrawdown < -0.1 ? "from-rose-900/30 to-slate-900/80" : "from-slate-800/50 to-slate-900/80"}
                accentColor={vitals.ytdMaxDrawdown < -0.1 ? "border-rose-500/30" : "border-white/10"}
            >
                <div className="space-y-2">
                    <span className={cn(
                        "text-3xl font-black tracking-tight block",
                        vitals.ytdMaxDrawdown < -0.1 ? "text-rose-400" : vitals.ytdMaxDrawdown < -0.05 ? "text-amber-400" : "text-emerald-400"
                    )}>
                        {formatPercent(vitals.ytdMaxDrawdown)}
                    </span>
                    <div className="flex items-center gap-2 text-xs">
                        <span className="text-gray-500">vs SPY:</span>
                        <span className="font-mono text-white font-bold bg-white/10 px-2 py-0.5 rounded">
                            {formatPercent(vitals.benchmarkYtdMaxDrawdown)}
                        </span>
                    </div>
                </div>
            </MetricCard>

            {/* Financing Impact */}
            <MetricCard
                title={`Financing Impact (${costTier.charAt(0).toUpperCase() + costTier.slice(1)})`}
                icon={PieChart}
                gradient="from-slate-800/40 to-slate-900/80"
                accentColor="border-indigo-500/20"
            >
                <div className="flex flex-col gap-3">
                    <div className="flex justify-between items-center bg-white/5 rounded-lg px-3 py-2 border border-white/5">
                        <span className="text-[11px] uppercase tracking-wider text-gray-400 font-bold flex items-center gap-1.5" title="Accumulated financing drag since Jan 1">
                            YTD Cost
                        </span>
                        <span className="font-mono text-lg font-black tracking-tight text-rose-400">
                            {vitals.ytdFinancingCost !== undefined ? formatPercent(-vitals.ytdFinancingCost) : "—"}
                        </span>
                    </div>
                    
                    <div className="flex justify-between items-center bg-white/5 rounded-lg px-3 py-2 border border-white/5 mt-0.5">
                        <span className="text-[11px] uppercase tracking-wider text-gray-400 font-bold flex items-center gap-1.5" title="Annualized estimate of combined margin & borrow fees">
                            Ann. Est
                        </span>
                        <span className="font-mono text-lg font-black tracking-tight text-amber-400">
                            {vitals.annualFinancingCost !== undefined ? formatPercent(-vitals.annualFinancingCost) : "—"}
                        </span>
                    </div>

                    <div className="flex justify-between items-center bg-white/5 rounded-lg px-3 py-2 border border-white/5 mt-0.5">
                        <span className="text-[11px] uppercase tracking-wider text-gray-400 font-bold flex items-center gap-1.5" title="Total gross exposure">
                            Gross Exp
                        </span>
                        <span className="font-mono text-lg font-black tracking-tight text-indigo-400">
                            {leverage ? (leverage.Gross_Exp * 100).toFixed(0) + "%" : "—"}
                        </span>
                    </div>
                </div>
            </MetricCard>
        </div>
    );
};
