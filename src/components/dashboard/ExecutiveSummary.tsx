
import React from 'react';
import { cn } from '../../lib/utils';
import type { Vitals } from '../../utils/finance';
import { TrendingUp, TrendingDown, Activity, Zap, Shield, BarChart3 } from 'lucide-react';

interface ExecutiveSummaryProps {
    vitals: Vitals;
}

export const ExecutiveSummary: React.FC<ExecutiveSummaryProps> = ({ vitals }) => {
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
            "relative overflow-hidden rounded-xl p-5",
            "bg-gradient-to-br", gradient,
            "border", accentColor,
            "backdrop-blur-xl shadow-lg",
            "transition-all duration-300 hover:shadow-xl hover:scale-[1.02]",
            "group"
        )}>
            {/* Subtle glow effect */}
            <div className="absolute inset-0 bg-gradient-to-br from-white/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />

            <div className="flex items-center gap-2 mb-3">
                <Icon className="h-4 w-4 text-gray-400" />
                <span className="text-xs text-gray-400 uppercase tracking-wider font-semibold">{title}</span>
            </div>
            {children}
        </div>
    );

    return (
        <div className="mb-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">

            {/* Market Conditions */}
            <MetricCard
                title="Market Conditions"
                icon={Activity}
                gradient="from-slate-800/60 to-slate-900/80"
                accentColor="border-blue-500/20"
            >
                <div className="space-y-3">
                    <div className="flex justify-between items-center">
                        <span className="text-sm text-gray-400">YTD Beta</span>
                        <span className="font-mono text-2xl font-bold text-white">{formatNumber(vitals.ytdBeta)}</span>
                    </div>
                    <div className="flex justify-between items-center">
                        <span className="text-sm text-gray-400">Regime</span>
                        <span className={cn(
                            "font-mono text-xs font-bold px-3 py-1 rounded-full",
                            vitals.ytdBeta > 1
                                ? "bg-gradient-to-r from-amber-500/30 to-orange-500/30 text-amber-400 border border-amber-500/30"
                                : "bg-gradient-to-r from-blue-500/30 to-cyan-500/30 text-blue-400 border border-blue-500/30"
                        )}>
                            {vitals.ytdBeta > 1 ? "⚡ Aggressive" : "🛡️ Defensive"}
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
                        )}>
                            {vitals.ytdReturn > 0 ? "+" : ""}{formatPercent(vitals.ytdReturn)}
                        </span>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs">
                        <span className="px-2 py-1 rounded-md bg-white/5 text-gray-400">
                            SPY <span className="text-white font-medium">{formatPercent(vitals.benchmarkYtd)}</span>
                        </span>
                        <span className="px-2 py-1 rounded-md bg-white/5 text-gray-400">
                            🌍 MSCI <span className="text-white font-medium">{formatPercent(vitals.msciYtd)}</span>
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
                    <span className="inline-block text-xs text-gray-400 bg-white/10 px-2 py-1 rounded-md">
                        incl. FX
                    </span>
                </div>
            </MetricCard>

            {/* Jensen's Alpha */}
            <MetricCard
                title="Jensen's Alpha"
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
                        <span className="text-xs text-gray-500 bg-white/5 px-2 py-0.5 rounded">Raw YTD</span>
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
        </div>
    );
};
