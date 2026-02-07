import React, { useState } from 'react';
import { cn } from '../../lib/utils';
import type { PeriodicReturn } from '../../utils/finance';
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface ReturnsHeatmapProps {
    periodicReturns: PeriodicReturn[];
}

type SortKey = 'ticker' | 'ytd' | 'ytdContribution' | 'r1m' | 'r1y' | 'r5y' | 'lastPrice' | 'volatility';
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

const getVolatilityColor = (val: number | null): string => {
    if (val === null || val === undefined) return 'bg-gray-800/50 text-gray-500';
    if (val > 0.80) return 'bg-rose-900/70 text-rose-200';  // >80% very high
    if (val > 0.50) return 'bg-amber-700/60 text-amber-200';  // >50% high
    if (val > 0.30) return 'bg-yellow-600/40 text-yellow-200';  // >30% moderate
    return 'bg-blue-600/30 text-blue-200';  // <30% low
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

const formatPrice = (val: number | null, currency: string = 'USD'): string => {
    if (val === null || val === undefined) return '—';
    const symbols: Record<string, string> = {
        'USD': '$', 'EUR': '€', 'GBP': '£', 'PLN': 'zł', 'SEK': 'kr', 'NOK': 'kr', 'CHF': 'Fr'
    };
    const symbol = symbols[currency] || currency + ' ';
    return `${symbol}${val.toFixed(2)}`;
};

const formatVolatility = (val: number | null): string => {
    if (val === null || val === undefined) return '—';
    return `${(val * 100).toFixed(0)}%`;
};

export const ReturnsHeatmap = ({ periodicReturns }: { periodicReturns: PeriodicReturn[] }) => {
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
            case 'sector': return null;
            case 'ytd': return row.ytd ?? null;
            case 'ytdContribution': return row.ytdContribution ?? null;
            case 'r1m': return row.r1m ?? null;
            case 'r1y': return row.r1y ?? null;
            case 'r5y': return row.r5y ?? null;
            case 'lastPrice': return row.lastPrice ?? null;
            case 'volatility': return row.volatility ?? null;
            default: return null;
        }
    };

    const sortedData = [...periodicReturns].sort((a, b) => {
        if (sortKey === 'ticker') {
            return sortDir === 'asc' ? a.ticker.localeCompare(b.ticker) : b.ticker.localeCompare(a.ticker);
        }
        if (sortKey === 'sector') {
            const sA = a.sector || '';
            const sB = b.sector || '';
            return sortDir === 'asc' ? sA.localeCompare(sB) : sB.localeCompare(sA);
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
        { key: 'sector', label: 'Sector' },
        { key: 'lastPrice', label: 'Price', tooltip: 'Last fetched price (USD)' },
        { key: 'ytdContribution', label: 'YTD Contrib', tooltip: 'Weight × Return × Direction' },
        { key: 'ytd', label: 'YTD' },
        { key: 'r1m', label: '1M' },
        { key: 'r1y', label: '1Y' },
        { key: 'r5y', label: '5Y' },
        { key: 'volatility', label: 'Vol', tooltip: 'Annualized volatility (std dev)' },
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

            <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-slate-900/95 backdrop-blur-sm z-10">
                        <tr className="border-b-2 border-white/20">
                            {columns.map(col => (
                                <th
                                    key={col.key}
                                    onClick={() => handleSort(col.key)}
                                    title={col.tooltip}
                                    className={cn(
                                        "px-4 py-3 text-left font-semibold cursor-pointer hover:bg-white/10 transition-colors whitespace-nowrap",
                                        col.key === 'ticker' ? "text-gray-200" : "text-gray-300 text-center",
                                        sortKey === col.key && "text-white bg-white/5"
                                    )}
                                >
                                    {col.label}
                                    <SortIcon columnKey={col.key} />
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                        {sortedData.map((row, idx) => (
                            <tr key={row.ticker} className={cn(
                                "hover:bg-white/10 transition-colors",
                                idx % 2 === 0 ? "bg-white/[0.02]" : ""
                            )}>
                                {/* Ticker with direction indicator */}
                                <td className="px-4 py-3 font-semibold text-white flex items-center gap-2">
                                    <span className="text-base">{row.ticker}</span>
                                    {row.direction === 'Long' && <ArrowUpRight className="h-4 w-4 text-emerald-400" />}
                                    {row.direction === 'Short' && <ArrowDownRight className="h-4 w-4 text-rose-400" />}
                                </td>

                                {/* Sector */}
                                <td className="px-4 py-3 text-left text-sm text-gray-400">
                                    {row.sector || '—'}
                                </td>

                                {/* Price */}
                                <td className="px-4 py-3 text-center font-mono text-sm text-gray-200 bg-white/[0.02]">
                                    {formatPrice(row.lastPrice, row.currency)}
                                </td>

                                {/* YTD Contribution */}
                                <td
                                    onMouseEnter={() => setHoveredCell({ ticker: row.ticker, period: 'ytdContribution' })}
                                    onMouseLeave={() => setHoveredCell(null)}
                                    className={cn(
                                        "px-4 py-3 text-center font-mono text-sm transition-all",
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
                                                "px-4 py-3 text-center font-mono text-sm transition-all",
                                                getReturnColor(val),
                                                isHovered && "ring-2 ring-white/50 scale-105"
                                            )}
                                        >
                                            {formatPercent(val)}
                                        </td>
                                    );
                                })}

                                {/* Volatility */}
                                <td
                                    onMouseEnter={() => setHoveredCell({ ticker: row.ticker, period: 'volatility' })}
                                    onMouseLeave={() => setHoveredCell(null)}
                                    className={cn(
                                        "px-4 py-3 text-center font-mono text-sm transition-all",
                                        getVolatilityColor(row.volatility),
                                        hoveredCell?.ticker === row.ticker && hoveredCell?.period === 'volatility' && "ring-2 ring-white/50 scale-105"
                                    )}
                                    title="Annualized volatility"
                                >
                                    {formatVolatility(row.volatility)}
                                </td>
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
