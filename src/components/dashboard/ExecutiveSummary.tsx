
import React from 'react';
import { cn } from '../../lib/utils';
import type { Vitals } from '../../utils/finance';

interface ExecutiveSummaryProps {
    vitals: Vitals;
}

export const ExecutiveSummary: React.FC<ExecutiveSummaryProps> = ({ vitals }) => {
    const formatPercent = (val: number | undefined) => typeof val === 'number' ? `${(val * 100).toFixed(2)}%` : 'N/A';
    const formatNumber = (val: number | undefined) => typeof val === 'number' ? val.toFixed(2) : 'N/A';

    return (
        <div className="mb-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-6 rounded-xl border border-white/10 bg-white/5 p-6 backdrop-blur-lg shadow-lg">

            {/* Market Conditions */}
            <div className="flex flex-col border-r border-white/10 pr-6 lg:last:border-0 relative">
                <span className="text-xs text-gray-400 uppercase tracking-wider mb-2 font-semibold">Market Conditions</span>
                <div className="flex justify-between items-center mb-1">
                    <span className="text-sm text-gray-300">YTD Beta</span>
                    <span className="font-mono text-lg font-bold text-white">{formatNumber(vitals.ytdBeta)}</span>
                </div>
                <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-300">Regime</span>
                    <span className={cn("font-mono text-sm font-bold px-2 py-0.5 rounded", vitals.ytdBeta > 1 ? "bg-amber-500/20 text-amber-400" : "bg-blue-500/20 text-blue-400")}>
                        {vitals.ytdBeta > 1 ? "Aggressive" : "Defensive"}
                    </span>
                </div>
            </div>

            {/* YTD Return */}
            <div className="flex flex-col border-r border-white/10 px-6 lg:last:border-0">
                <span className="text-xs text-gray-400 uppercase tracking-wider mb-2 font-semibold">2026 YTD Return</span>
                <div className="flex items-baseline gap-3 mb-2">
                    <span className={cn("text-3xl font-bold tracking-tight", vitals.ytdReturn >= 0 ? "text-emerald-400" : "text-rose-400")}>
                        {vitals.ytdReturn > 0 ? "+" : ""}{formatPercent(vitals.ytdReturn)}
                    </span>
                    <span className="text-xs text-gray-400 font-medium">SPY {formatPercent(vitals.benchmarkYtd)}</span>
                </div>
                <div className="flex gap-4 text-xs">

                    <span className="text-blue-300 font-medium flex items-center gap-1">
                        🌍 MSCI <span className="text-white">{formatPercent(vitals.msciYtd)}</span>
                    </span>
                </div>
            </div>

            {/* PLN Return */}
            <div className="flex flex-col border-r border-white/10 px-6 lg:last:border-0">
                <span className="text-xs text-gray-400 uppercase tracking-wider mb-2 font-semibold">🇵🇱 YTD in PLN</span>
                <div className="flex items-baseline gap-3">
                    <span className={cn("text-3xl font-bold tracking-tight", vitals.ytdReturnPln >= 0 ? "text-emerald-400" : "text-rose-400")}>
                        {vitals.ytdReturnPln > 0 ? "+" : ""}{formatPercent(vitals.ytdReturnPln)}
                    </span>
                    <span className="text-xs text-gray-500 font-medium bg-white/10 px-2 py-0.5 rounded">incl. FX</span>
                </div>
            </div>

            {/* Jensen's Alpha */}
            <div className="flex flex-col border-r border-white/10 px-6 lg:last:border-0">
                <span className="text-xs text-amber-400 uppercase tracking-wider mb-2 font-bold">Jensen's Alpha</span>
                <div className="flex flex-col gap-1">
                    <div className="flex items-baseline gap-3">
                        <span className={cn("text-3xl font-bold tracking-tight", vitals.ytdAlpha >= 0 ? "text-emerald-400" : "text-rose-400")}>
                            {vitals.ytdAlpha > 0 ? "+" : ""}{formatPercent(vitals.ytdAlpha)}
                        </span>
                        <span className="text-xs text-gray-400">YTD</span>
                    </div>
                </div>
            </div>

            {/* Risk Efficiency */}
            <div className="flex flex-col border-r border-white/10 px-6 lg:last:border-0 relative">
                <span className="text-xs text-gray-400 uppercase tracking-wider mb-2 font-semibold">YTD Efficiency (Sharpe)</span>
                <div className="flex items-baseline gap-3 mb-1">
                    <span className={cn("text-3xl font-bold tracking-tight", vitals.ytdSharpe > 1 ? "text-emerald-400" : "text-white")}>
                        {formatNumber(vitals.ytdSharpe)}
                    </span>
                    <span className="text-xs text-gray-400">vs {formatNumber(vitals.benchmarkYtdSharpe)}</span>
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-500 mt-1">
                    <span>Hist Avg:</span>
                    <span className="font-mono text-amber-500 font-bold">{formatNumber(vitals.sharpe)}</span>
                </div>
            </div>

            {/* YTD Max Drawdown */}
            <div className="flex flex-col pl-6">
                <span className="text-xs text-gray-400 uppercase tracking-wider mb-2 font-semibold">YTD Max Drawdown</span>
                <div className="flex items-baseline gap-3 mb-1">
                    <span className={cn("text-3xl font-bold tracking-tight", vitals.ytdMaxDrawdown < -0.1 ? "text-rose-400" : "text-white")}>
                        {formatPercent(vitals.ytdMaxDrawdown)}
                    </span>
                </div>
                <div className="flex justify-between items-center text-xs text-gray-400 mt-1">
                    <span>vs SPY:</span>
                    <span className="font-mono text-white font-bold">{formatPercent(vitals.benchmarkYtdMaxDrawdown)}</span>
                </div>
            </div>
        </div>
    );
};
