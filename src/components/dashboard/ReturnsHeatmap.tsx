import React, { useState } from 'react';
import { cn } from '../../lib/utils';
import type { PeriodicReturn } from '../../utils/finance';
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface ReturnsHeatmapProps {
    periodicReturns: PeriodicReturn[];
}

type SortKey = 'ticker' | 'ytd' | 'ytdContribution' | 'r1m' | 'r1y' | 'r5y';
type SortDir = 'asc' | 'desc';

const getReturnColor = (val: number | null): string => {
    if (val === null || val === undefined) return 'bg-gray-800/50 text-gray-500';

    if (val <= -0.10) return 'bg-red-900/80 text-red-200';
    if (val <= -0.05) return 'bg-red-700/70 text-red-100';
    if (val <= -0.02) return 'bg-red-600/50 text-red-100';
    if (val < 0) return 'bg-red-500/30 text-red-200';
    if (val === 0) return 'bg-gray-700/50 text-gray-300';
    if (val < 0.02) return 'bg-emerald-500/30 text-emerald-200';
    if (val < 0.05) return 'bg-emerald-600/50 text-emerald-100';
    if (val < 0.10) return 'bg-emerald-700/70 text-emerald-100';
    return 'bg-emerald-900/80 text-emerald-200';
};

const formatPercent = (val: number | null): string => {
    if (val === null || val === undefined) return '—';
    const sign = val > 0 ? '+' : '';
    return `${sign}${(val * 100).toFixed(1)}%`;
};

const formatContribution = (val: number | null): string => {
    if (val === null || val === undefined) return '—';
    const sign = val > 0 ? '+' : '';
    return `${sign}${(val * 100).toFixed(2)}%`;
};

export const ReturnsHeatmap: React.FC<ReturnsHeatmapProps> = ({ periodicReturns }) => {
    const [sortKey, setSortKey] = useState<SortKey>('ytdContribution');
    const [sortDir, setSortDir] = useState<SortDir>('desc');
    const [hoveredCell, setHoveredCell] = useState<{ ticker: string; period: string } | null>(null);

    const handleSort = (key: SortKey) => {
        if (sortKey === key) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
        } else {
            setSortKey(key);
            setSortDir('desc');
        }
    };

    const getValue = (row: PeriodicReturn, key: SortKey): number | null => {
        switch (key) {
            case 'ticker': return null;
            case 'ytd': return row.ytd ?? null;
            case 'ytdContribution': return row.ytdContribution ?? null;
            case 'r1m': return row.r1m ?? null;
            case 'r1y': return row.r1y ?? null;
            case 'r5y': return row.r5y ?? null;
            default: return null;
        }
    };

    const sortedData = [...periodicReturns].sort((a, b) => {
        if (sortKey === 'ticker') {
            return sortDir === 'asc'
                ? a.ticker.localeCompare(b.ticker)
                : b.ticker.localeCompare(a.ticker);
        }

        const aVal = getValue(a, sortKey);
        const bVal = getValue(b, sortKey);

        if (aVal === null && bVal === null) return 0;
        if (aVal === null) return 1;
        if (bVal === null) return -1;
        return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
    });

    const columns: { key: SortKey; label: string; tooltip?: string }[] = [
        { key: 'ticker', label: 'Ticker' },
        { key: 'ytdContribution', label: 'YTD Contrib', tooltip: 'Weight × Return × Direction' },
        { key: 'ytd', label: 'YTD' },
        { key: 'r1m', label: '1M' },
        { key: 'r1y', label: '1Y' },
        { key: 'r5y', label: '5Y' },
    ];

    const SortIcon = ({ columnKey }: { columnKey: SortKey }) => {
        if (sortKey !== columnKey) return null;
        return sortDir === 'desc'
            ? <TrendingDown className="h-3 w-3 inline ml-1" />
            : <TrendingUp className="h-3 w-3 inline ml-1" />;
    };

    return (
        <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-lg">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                📊 Returns Heatmap & Portfolio Contribution
                <span className="text-xs text-gray-400 font-normal">(Click headers to sort)</span>
            </h3>

            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="border-b border-white/10">
                            {columns.map(col => (
                                <th
                                    key={col.key}
                                    onClick={() => handleSort(col.key)}
                                    title={col.tooltip}
                                    className={cn(
                                        "px-3 py-2 text-left font-medium cursor-pointer hover:bg-white/5 transition-colors whitespace-nowrap",
                                        col.key === 'ticker' ? "text-gray-300" : "text-gray-400 text-center",
                                        sortKey === col.key && "text-white"
                                    )}
                                >
                                    {col.label}
                                    <SortIcon columnKey={col.key} />
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                        {sortedData.map((row) => (
                            <tr key={row.ticker} className="hover:bg-white/5 transition-colors">
                                {/* Ticker with direction indicator */}
                                <td className="px-3 py-2 font-medium text-white flex items-center gap-1">
                                    {row.ticker}
                                    {row.direction === 'Long' && <ArrowUpRight className="h-3 w-3 text-emerald-400" />}
                                    {row.direction === 'Short' && <ArrowDownRight className="h-3 w-3 text-rose-400" />}
                                </td>

                                {/* YTD Contribution */}
                                <td
                                    onMouseEnter={() => setHoveredCell({ ticker: row.ticker, period: 'ytdContribution' })}
                                    onMouseLeave={() => setHoveredCell(null)}
                                    className={cn(
                                        "px-3 py-2 text-center font-mono text-sm transition-all",
                                        getReturnColor(row.ytdContribution),
                                        hoveredCell?.ticker === row.ticker && hoveredCell?.period === 'ytdContribution' && "ring-2 ring-white/50 scale-105"
                                    )}
                                    title={row.weight ? `Weight: ${(row.weight * 100).toFixed(0)}%` : undefined}
                                >
                                    {formatContribution(row.ytdContribution)}
                                </td>

                                {/* Return Periods */}
                                {(['ytd', 'r1m', 'r1y', 'r5y'] as const).map((period) => {
                                    const val = period === 'ytd' ? row.ytd : row[period];
                                    const isHovered = hoveredCell?.ticker === row.ticker && hoveredCell?.period === period;

                                    return (
                                        <td
                                            key={period}
                                            onMouseEnter={() => setHoveredCell({ ticker: row.ticker, period })}
                                            onMouseLeave={() => setHoveredCell(null)}
                                            className={cn(
                                                "px-3 py-2 text-center font-mono text-sm transition-all",
                                                getReturnColor(val),
                                                isHovered && "ring-2 ring-white/50 scale-105"
                                            )}
                                        >
                                            {formatPercent(val)}
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Legend */}
            <div className="mt-4 flex flex-wrap items-center justify-center gap-3 text-xs text-gray-400">
                <div className="flex items-center gap-1">
                    <ArrowUpRight className="h-3 w-3 text-emerald-400" />
                    <span>Long</span>
                </div>
                <div className="flex items-center gap-1">
                    <ArrowDownRight className="h-3 w-3 text-rose-400" />
                    <span>Short</span>
                </div>
                <span className="text-gray-600">|</span>
                <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded bg-red-900/80" />
                    <span>{"< -10%"}</span>
                </div>
                <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded bg-gray-700/50" />
                    <span>0%</span>
                </div>
                <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded bg-emerald-900/80" />
                    <span>{"> +10%"}</span>
                </div>
            </div>
        </div>
    );
};
