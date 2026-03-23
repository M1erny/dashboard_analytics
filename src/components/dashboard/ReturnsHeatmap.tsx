import { useState, useMemo } from 'react';
import { cn } from '../../lib/utils';
import type { PeriodicReturn } from '../../utils/finance';
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight, ChevronUp, ChevronDown, BarChart3, Flame, Zap } from 'lucide-react';

type SortKey = 'ticker' | 'ytd' | 'ytdContribution' | 'r7dContribution' | 'r1dContribution' | 'r1d' | 'r7d' | 'r1m' | 'r1y' | 'lastPrice' | 'volatility' | 'volumeIndicator' | 'currentWeight';
type SortDir = 'asc' | 'desc';

// ─── Color System ────────────────────────────────────────────
const getReturnColor = (val: number | null): string => {
    if (val === null || val === undefined) return '';
    if (val <= -0.10) return 'bg-gradient-to-br from-red-950/90 to-red-900/70 text-red-200';
    if (val <= -0.05) return 'bg-gradient-to-br from-red-900/70 to-red-800/50 text-red-200';
    if (val <= -0.02) return 'bg-red-800/40 text-red-300';
    if (val < 0)      return 'bg-red-700/20 text-red-300';
    if (val === 0)    return 'text-gray-500';
    if (val < 0.02)   return 'bg-emerald-700/20 text-emerald-300';
    if (val < 0.05)   return 'bg-emerald-800/40 text-emerald-200';
    if (val < 0.10)   return 'bg-gradient-to-br from-emerald-800/50 to-emerald-900/70 text-emerald-200';
    return 'bg-gradient-to-br from-emerald-900/70 to-emerald-950/90 text-emerald-200';
};

const getContribColor = (val: number | null): string => {
    if (val === null || val === undefined) return '';
    if (val <= -0.005) return 'bg-gradient-to-r from-red-950/80 to-red-900/60 text-red-200';
    if (val < 0)       return 'bg-red-800/25 text-red-300';
    if (val === 0)     return 'text-gray-500';
    if (val < 0.005)   return 'bg-emerald-800/25 text-emerald-300';
    return 'bg-gradient-to-r from-emerald-900/60 to-emerald-950/80 text-emerald-200';
};

const getVolatilityColor = (val: number | null): string => {
    if (val === null || val === undefined) return '';
    if (val > 0.80) return 'bg-rose-900/50 text-rose-300';
    if (val > 0.50) return 'bg-amber-800/40 text-amber-300';
    if (val > 0.30) return 'bg-yellow-800/30 text-yellow-300';
    return 'bg-sky-900/25 text-sky-300';
};

const getVolumeColor = (val: number | null): string => {
    if (val === null || val === undefined) return '';
    if (val > 2.0) return 'bg-violet-800/50 text-violet-200';
    if (val > 1.5) return 'bg-amber-800/40 text-amber-200';
    if (val > 1.1) return 'bg-emerald-800/30 text-emerald-300';
    if (val > 0.9) return 'text-gray-400';
    return 'bg-sky-900/25 text-sky-300';
};

// ─── Formatters ──────────────────────────────────────────────
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
        'USD': '$', 'EUR': '€', 'GBP': '£', 'PLN': 'zł', 'SEK': 'kr', 'NOK': 'kr', 'CHF': 'Fr', 'JPY': '¥', 'KRW': '₩', 'DKK': 'kr'
    };
    const symbol = symbols[currency] || currency + ' ';
    // Large prices (JPY, KRW) don't need decimals
    const decimals = val > 1000 ? 0 : 2;
    return `${symbol}${val.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
};

const formatVolatility = (val: number | null): string => {
    if (val === null || val === undefined) return '—';
    return `${(val * 100).toFixed(0)}%`;
};

// ─── Contribution Bar (visual magnitude indicator) ───────────
const ContribBar = ({ value, maxAbsValue }: { value: number | null; maxAbsValue: number }) => {
    if (value === null || value === undefined || maxAbsValue === 0) return null;
    const pct = Math.min(Math.abs(value) / maxAbsValue, 1) * 100;
    const isPositive = value >= 0;
    return (
        <div className="absolute bottom-0 left-0 right-0 h-[3px] overflow-hidden rounded-b opacity-60">
            <div
                className={cn(
                    "h-full rounded-full transition-all duration-500",
                    isPositive ? "bg-emerald-400" : "bg-red-400"
                )}
                style={{ width: `${pct}%`, marginLeft: isPositive ? 0 : 'auto', marginRight: isPositive ? 'auto' : 0 }}
            />
        </div>
    );
};

// ─── Weight Bar ──────────────────────────────────────────────
const WeightBar = ({ current, initial }: { current: number | null; initial: number | null }) => {
    if (current === null || current === undefined) return <span className="text-gray-600">—</span>;
    const pct = Math.min(current * 100, 30); // cap at 30% for bar width
    const barWidth = (pct / 30) * 100;
    const drifted = initial !== null && initial !== undefined && Math.abs(current - initial) > 0.005;
    return (
        <div className="flex flex-col items-center gap-0.5 min-w-[60px]">
            <div className="flex items-baseline gap-1">
                <span className={cn("font-mono text-sm font-semibold", drifted ? "text-amber-300" : "text-gray-200")}>
                    {(current * 100).toFixed(1)}%
                </span>
            </div>
            <div className="w-full h-[3px] bg-white/5 rounded-full overflow-hidden">
                <div
                    className={cn("h-full rounded-full transition-all duration-700", drifted ? "bg-amber-500/60" : "bg-white/20")}
                    style={{ width: `${barWidth}%` }}
                />
            </div>
            {initial !== null && initial !== undefined && (
                <span className="text-[9px] text-gray-600 font-mono leading-none">
                    target {(initial * 100).toFixed(0)}%
                </span>
            )}
        </div>
    );
};

// ─── Direction Badge ─────────────────────────────────────────
const DirectionBadge = ({ direction }: { direction: 'Long' | 'Short' | null }) => {
    if (!direction) return null;
    return direction === 'Long' ? (
        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
            <ArrowUpRight className="h-2.5 w-2.5" /> L
        </span>
    ) : (
        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/20">
            <ArrowDownRight className="h-2.5 w-2.5" /> S
        </span>
    );
};

// ─── Column Group Definitions ────────────────────────────────
interface ColumnDef {
    key: SortKey;
    label: string;
    tooltip?: string;
    group: 'position' | 'contribution' | 'returns' | 'risk';
}

const columns: ColumnDef[] = [
    { key: 'ticker',           label: 'Ticker',     group: 'position' },
    { key: 'lastPrice',        label: 'Price',      group: 'position', tooltip: 'Last fetched price' },
    { key: 'currentWeight',    label: 'Weight',     group: 'position', tooltip: 'Current drifted weight' },
    { key: 'ytdContribution',  label: 'YTD',        group: 'contribution', tooltip: 'YTD portfolio contribution' },
    { key: 'r7dContribution',  label: '7D',         group: 'contribution', tooltip: '7-day portfolio contribution' },
    { key: 'r1dContribution',  label: '1D',         group: 'contribution', tooltip: '1-day portfolio contribution' },
    { key: 'ytd',              label: 'YTD',        group: 'returns' },
    { key: 'r7d',              label: '7D',         group: 'returns', tooltip: '7-day return' },
    { key: 'r1m',              label: '1M',         group: 'returns' },
    { key: 'r1y',              label: '1Y',         group: 'returns' },
    { key: 'volatility',       label: 'Vol',        group: 'risk', tooltip: 'Annualized volatility' },
    { key: 'volumeIndicator',  label: 'Vol Ratio',  group: 'risk', tooltip: '7D avg volume ÷ YTD avg volume' },
];

const groupMeta: Record<string, { label: string; icon: React.ReactNode; colSpan: number; borderClass: string }> = {
    position:     { label: 'Position',      icon: <BarChart3 className="h-3 w-3" />, colSpan: 3, borderClass: 'border-l-0' },
    contribution: { label: 'Contribution',  icon: <Zap className="h-3 w-3" />,       colSpan: 3, borderClass: 'border-l border-white/10' },
    returns:      { label: 'Returns',       icon: <TrendingUp className="h-3 w-3" />,colSpan: 4, borderClass: 'border-l border-white/10' },
    risk:         { label: 'Risk',          icon: <Flame className="h-3 w-3" />,     colSpan: 2, borderClass: 'border-l border-white/10' },
};

// ─── Main Component ──────────────────────────────────────────
export const ReturnsHeatmap = ({ periodicReturns }: { periodicReturns: PeriodicReturn[] }) => {
    const [sortKey, setSortKey] = useState<SortKey>('ytdContribution');
    const [sortDir, setSortDir] = useState<SortDir>('desc');
    const [hoveredRow, setHoveredRow] = useState<string | null>(null);

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
            case 'r7dContribution': return row.r7dContribution ?? null;
            case 'r1dContribution': return row.r1dContribution ?? null;
            case 'r1d': return row.r1d ?? null;
            case 'r7d': return row.r7d ?? null;
            case 'r1m': return row.r1m ?? null;
            case 'r1y': return row.r1y ?? null;
            case 'lastPrice': return row.lastPrice ?? null;
            case 'volatility': return row.volatility ?? null;
            case 'volumeIndicator': return row.volumeIndicator ?? null;
            case 'currentWeight': return row.currentWeight ?? null;
            default: return null;
        }
    };

    const sortedData = useMemo(() => {
        return [...periodicReturns].sort((a, b) => {
            if (sortKey === 'ticker') {
                return sortDir === 'asc' ? a.ticker.localeCompare(b.ticker) : b.ticker.localeCompare(a.ticker);
            }
            const aVal = getValue(a, sortKey);
            const bVal = getValue(b, sortKey);
            if (aVal === null && bVal === null) return 0;
            if (aVal === null) return 1;
            if (bVal === null) return -1;
            return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
        });
    }, [periodicReturns, sortKey, sortDir]);

    // Compute max absolute contribution for bar scaling
    const maxAbsContrib = useMemo(() => {
        let max = 0;
        for (const r of periodicReturns) {
            if (r.ytdContribution !== null && r.ytdContribution !== undefined) max = Math.max(max, Math.abs(r.ytdContribution));
            if (r.r7dContribution !== null && r.r7dContribution !== undefined) max = Math.max(max, Math.abs(r.r7dContribution));
            if (r.r1dContribution !== null && r.r1dContribution !== undefined) max = Math.max(max, Math.abs(r.r1dContribution));
        }
        return max || 0.01;
    }, [periodicReturns]);

    // Summary row aggregation
    const summary = useMemo(() => {
        let ytdC = 0, r7dC = 0, r1dC = 0;
        let longCount = 0, shortCount = 0;
        for (const r of periodicReturns) {
            if (r.ytdContribution != null) ytdC += r.ytdContribution;
            if (r.r7dContribution != null) r7dC += r.r7dContribution;
            if (r.r1dContribution != null) r1dC += r.r1dContribution;
            if (r.direction === 'Long') longCount++;
            if (r.direction === 'Short') shortCount++;
        }
        return { ytdC, r7dC, r1dC, longCount, shortCount, total: periodicReturns.length };
    }, [periodicReturns]);

    const SortIndicator = ({ columnKey }: { columnKey: SortKey }) => {
        if (sortKey !== columnKey) {
            return <span className="inline-block ml-0.5 opacity-0 group-hover:opacity-30 transition-opacity"><ChevronDown className="h-3 w-3 inline" /></span>;
        }
        return sortDir === 'desc'
            ? <ChevronDown className="h-3 w-3 inline ml-0.5 text-blue-400" />
            : <ChevronUp className="h-3 w-3 inline ml-0.5 text-blue-400" />;
    };

    const renderCell = (row: PeriodicReturn, col: ColumnDef, isFirstInGroup: boolean) => {
        const isHovered = hoveredRow === row.ticker;
        const groupBorder = isFirstInGroup && col.group !== 'position' ? "border-l border-white/[0.04]" : "";

        switch (col.key) {
            case 'ticker':
                return (
                    <td key={col.key} className={cn("px-3 py-2.5 whitespace-nowrap sticky left-0 z-[5] bg-slate-950/95 backdrop-blur-sm", groupBorder)}>
                        <div className="flex items-center gap-2">
                            <span className={cn("font-semibold text-[13px] tracking-wide transition-colors", isHovered ? "text-white" : "text-gray-200")}>
                                {row.ticker}
                            </span>
                            <DirectionBadge direction={row.direction} />
                        </div>
                    </td>
                );
            case 'lastPrice':
                return (
                    <td key={col.key} className={cn("px-3 py-2.5 text-right font-mono text-[13px] text-gray-300 whitespace-nowrap", groupBorder)}>
                        {formatPrice(row.lastPrice, row.currency)}
                    </td>
                );
            case 'currentWeight':
                return (
                    <td key={col.key} className={cn("px-3 py-2.5", groupBorder)}>
                        <WeightBar current={row.currentWeight} initial={row.weight} />
                    </td>
                );
            case 'ytdContribution':
            case 'r7dContribution':
            case 'r1dContribution': {
                const val = col.key === 'ytdContribution' ? row.ytdContribution :
                            col.key === 'r7dContribution' ? row.r7dContribution : row.r1dContribution;
                return (
                    <td key={col.key} className={cn(
                        "px-3 py-2.5 text-center font-mono text-[13px] relative transition-all duration-200",
                        getContribColor(val),
                        isHovered && "brightness-125",
                        groupBorder
                    )}>
                        <span className="relative z-[1]">{formatContribution(val)}</span>
                        <ContribBar value={val} maxAbsValue={maxAbsContrib} />
                    </td>
                );
            }
            case 'ytd':
            case 'r7d':
            case 'r1m':
            case 'r1y':
            case 'r1d': {
                const val = col.key === 'ytd' ? row.ytd : row[col.key as 'r7d' | 'r1m' | 'r1y' | 'r1d'];
                return (
                    <td key={col.key} className={cn(
                        "px-3 py-2.5 text-center font-mono text-[13px] transition-all duration-200",
                        getReturnColor(val),
                        isHovered && "brightness-125",
                        groupBorder
                    )}>
                        {formatPercent(val)}
                    </td>
                );
            }
            case 'volatility':
                return (
                    <td key={col.key} className={cn(
                        "px-3 py-2.5 text-center font-mono text-[13px] transition-all duration-200",
                        getVolatilityColor(row.volatility),
                        isHovered && "brightness-125",
                        groupBorder
                    )}>
                        {formatVolatility(row.volatility)}
                    </td>
                );
            case 'volumeIndicator':
                return (
                    <td key={col.key} className={cn(
                        "px-3 py-2.5 text-center font-mono text-[13px] transition-all duration-200",
                        getVolumeColor(row.volumeIndicator),
                        isHovered && "brightness-125",
                        groupBorder
                    )}
                    title={row.volumeIndicator ? `7D avg is ${(row.volumeIndicator * 100).toFixed(0)}% of YTD avg` : undefined}
                    >
                        {row.volumeIndicator != null ? `${row.volumeIndicator.toFixed(2)}×` : '—'}
                    </td>
                );
            default:
                return <td key={col.key} className="px-3 py-2.5 text-gray-600">—</td>;
        }
    };

    return (
        <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-slate-900/80 to-slate-950/90 backdrop-blur-xl shadow-2xl shadow-black/40 overflow-hidden">
            {/* Header Bar */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.06] bg-white/[0.02]">
                <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10">
                        <BarChart3 className="h-4 w-4 text-blue-400" />
                    </div>
                    <div>
                        <h3 className="text-[15px] font-semibold text-white tracking-tight">Returns Heatmap</h3>
                        <p className="text-[11px] text-gray-500 mt-0.5">Portfolio contribution & performance matrix</p>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    {/* Quick stats pills */}
                    <div className="hidden sm:flex items-center gap-2">
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-[11px] font-mono text-emerald-400">
                            <ArrowUpRight className="h-3 w-3" /> {summary.longCount} longs
                        </span>
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-rose-500/10 border border-rose-500/20 text-[11px] font-mono text-rose-400">
                            <ArrowDownRight className="h-3 w-3" /> {summary.shortCount} shorts
                        </span>
                    </div>
                    <span className="text-[11px] text-gray-600 font-mono">{summary.total} positions</span>
                </div>
            </div>

            {/* Summary Strip */}
            <div className="grid grid-cols-3 divide-x divide-white/[0.06] border-b border-white/[0.06] bg-white/[0.015]">
                {[
                    { label: 'YTD Impact', value: summary.ytdC, icon: <TrendingUp className="h-3.5 w-3.5" /> },
                    { label: '7D Impact', value: summary.r7dC, icon: <Zap className="h-3.5 w-3.5" /> },
                    { label: '1D Impact', value: summary.r1dC, icon: <Flame className="h-3.5 w-3.5" /> },
                ].map(item => (
                    <div key={item.label} className="flex items-center justify-center gap-2.5 px-4 py-2.5">
                        <span className={cn("p-1 rounded", item.value >= 0 ? "text-emerald-400 bg-emerald-500/10" : "text-red-400 bg-red-500/10")}>
                            {item.icon}
                        </span>
                        <div className="flex flex-col">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">{item.label}</span>
                            <span className={cn(
                                "font-mono text-sm font-bold tracking-tight",
                                item.value > 0 ? "text-emerald-400" : item.value < 0 ? "text-red-400" : "text-gray-400"
                            )}>
                                {item.value > 0 ? '+' : ''}{(item.value * 100).toFixed(2)}%
                            </span>
                        </div>
                    </div>
                ))}
            </div>

            {/* Table */}
            <div className="overflow-x-auto max-h-[520px] overflow-y-auto scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
                <table className="w-full text-sm border-collapse">
                    {/* Group Header Row */}
                    <thead className="sticky top-0 z-20">
                        <tr className="bg-slate-950/98 backdrop-blur-md">
                            {Object.entries(groupMeta).map(([key, meta]) => (
                                <th
                                    key={key}
                                    colSpan={meta.colSpan}
                                    className={cn(
                                        "px-3 py-1.5 text-[10px] uppercase tracking-[0.12em] font-semibold text-gray-500",
                                        meta.borderClass,
                                        key === 'position' && "text-left"
                                    )}
                                >
                                    <div className={cn("flex items-center gap-1.5", key !== 'position' && "justify-center")}>
                                        {meta.icon}
                                        {meta.label}
                                    </div>
                                </th>
                            ))}
                        </tr>
                        {/* Column Header Row */}
                        <tr className="bg-slate-950/95 backdrop-blur-md border-b border-white/10">
                            {columns.map((col, i) => {
                                const isFirstInGroup = i === 0 || columns[i - 1].group !== col.group;
                                return (
                                    <th
                                        key={col.key}
                                        onClick={() => handleSort(col.key)}
                                        title={col.tooltip}
                                        className={cn(
                                            "group px-3 py-2 font-medium cursor-pointer select-none whitespace-nowrap transition-all duration-150",
                                            "hover:bg-white/[0.04] active:bg-white/[0.08]",
                                            col.key === 'ticker' ? "text-left text-gray-300 sticky left-0 z-[15] bg-slate-950/95" : "text-center text-gray-400",
                                            sortKey === col.key && "text-blue-400 bg-white/[0.03]",
                                            isFirstInGroup && col.group !== 'position' && "border-l border-white/[0.06]",
                                            "text-[12px]"
                                        )}
                                    >
                                        {col.label}
                                        <SortIndicator columnKey={col.key} />
                                    </th>
                                );
                            })}
                        </tr>
                    </thead>
                    <tbody>
                        {sortedData.map((row, idx) => (
                            <tr
                                key={row.ticker}
                                onMouseEnter={() => setHoveredRow(row.ticker)}
                                onMouseLeave={() => setHoveredRow(null)}
                                className={cn(
                                    "transition-all duration-150 border-b border-white/[0.03]",
                                    hoveredRow === row.ticker ? "bg-white/[0.06]" : idx % 2 === 0 ? "bg-white/[0.015]" : "bg-transparent"
                                )}
                            >
                                {columns.map((col, i) => {
                                    const isFirstInGroup = i === 0 || columns[i - 1].group !== col.group;
                                    return renderCell(row, col, isFirstInGroup);
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Footer Legend */}
            <div className="flex items-center justify-between px-5 py-2.5 border-t border-white/[0.06] bg-white/[0.015]">
                <div className="flex items-center gap-4 text-[10px] text-gray-500">
                    <span className="flex items-center gap-1.5">
                        <span className="w-5 h-2 rounded-sm bg-gradient-to-r from-red-900/80 to-red-800/60" />
                        Loss
                    </span>
                    <span className="flex items-center gap-1.5">
                        <span className="w-5 h-2 rounded-sm bg-gray-700/40" />
                        Flat
                    </span>
                    <span className="flex items-center gap-1.5">
                        <span className="w-5 h-2 rounded-sm bg-gradient-to-r from-emerald-800/60 to-emerald-900/80" />
                        Gain
                    </span>
                </div>
                <span className="text-[10px] text-gray-600 font-mono">Click headers to sort</span>
            </div>
        </div>
    );
};
