import React, { useState, useMemo, useCallback, useRef } from 'react';
import { cn } from '../../lib/utils';
import type { PeriodicReturn, RiskAttribution, Vitals } from '../../utils/finance';
import { TrendingUp, ArrowUpRight, ArrowDownRight, ChevronUp, ChevronDown, BarChart3, Flame, Zap, Target, Trophy, TrendingDown, Activity, GripVertical, RotateCcw } from 'lucide-react';

type SortKey = 'ticker' | 'ytd' | 'ytdContribution' | 'sinceRebalanceContribution' | 'r7dContribution' | 'r1dContribution' | 'r1d' | 'r7d' | 'r1m' | 'r1y' | 'lastPrice' | 'volatility' | 'volumeIndicator' | 'currentWeight' | 'entryPrice' | 'rSinceEntry' | 'volatilityContribution';
type SortDir = 'asc' | 'desc';
type ColumnGroup = 'position' | 'contribution' | 'returns' | 'risk';

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

const getRiskContribColor = (val: number | null): string => {
    if (val === null || val === undefined) return '';
    if (val > 0.20) return 'bg-rose-950/40 text-rose-300';
    if (val > 0.10) return 'bg-amber-950/30 text-amber-300';
    if (val > 0.0)  return 'bg-sky-950/25 text-sky-300';
    return 'bg-emerald-950/40 text-emerald-300';
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

const formatRiskContrib = (val: number | null): string => {
    if (val === null || val === undefined) return '—';
    const sign = val > 0 ? '+' : '';
    return `${sign}${(val * 100).toFixed(1)}%`;
};

const getSinceRebalanceDisplayContribution = (row: PeriodicReturn): number | null => {
    return row.sinceRebalanceContributionYtdBasis ?? row.sinceRebalanceContribution ?? null;
};

// ─── Contribution Bar (visual magnitude indicator) ───────────
const ContribBar = ({ value, maxAbsValue }: { value: number | null; maxAbsValue: number }) => {
    if (value === null || value === undefined || maxAbsValue === 0) return null;
    const pct = Math.min(Math.abs(value) / maxAbsValue, 1) * 100;
    const isPositive = value >= 0;
    return (
        <div className="absolute bottom-0 left-0 right-0 h-[4px] overflow-hidden rounded-b">
            <div
                className={cn(
                    "h-full rounded-full transition-all duration-700 ease-out",
                    isPositive
                        ? "bg-gradient-to-r from-emerald-400/80 to-emerald-500/60 shadow-[0_0_6px_rgba(52,211,153,0.3)]"
                        : "bg-gradient-to-r from-red-500/60 to-red-400/80 shadow-[0_0_6px_rgba(239,68,68,0.3)]"
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
    
    let textColor = "text-gray-200";
    let barColor = "bg-white/20";
    
    if (initial !== null && initial !== undefined) {
        const drift = Math.abs(current - initial);
        if (drift > 0.04) {
            textColor = "text-rose-400";
            barColor = "bg-rose-500/80";
        } else if (drift > 0.02) {
            textColor = "text-orange-400";
            barColor = "bg-orange-500/70";
        } else if (drift > 0.005) {
            textColor = "text-amber-300";
            barColor = "bg-amber-500/60";
        }
    }

    return (
        <div className="flex flex-col items-center gap-0.5 min-w-[60px]">
            <div className="flex items-baseline gap-1">
                <span className={cn("font-mono text-sm font-semibold", textColor)}>
                    {(current * 100).toFixed(1)}%
                </span>
            </div>
            <div className="w-full h-[3px] bg-white/5 rounded-full overflow-hidden">
                <div
                    className={cn("h-full rounded-full transition-all duration-700", barColor)}
                    style={{ width: `${barWidth}%` }}
                />
            </div>
            {initial !== null && initial !== undefined && (
                <div className="flex items-center gap-0.5 mt-0.5">
                    <span className="text-[9px] text-gray-500 font-mono leading-none">
                        target {(initial * 100).toFixed(0)}%
                    </span>
                    {Math.abs(current - initial) > 0.005 && (
                        <span className={cn("text-[8px] leading-none", current > initial ? "text-amber-500" : "text-sky-500")}>
                            {current > initial ? '▲' : '▼'}
                        </span>
                    )}
                </div>
            )}
        </div>
    );
};

// ─── Direction Badge ─────────────────────────────────────────
const DirectionBadge = ({ direction, status }: { direction: 'Long' | 'Short' | null; status?: 'Active' | 'Exited' | 'Planned' }) => {
    if (status === 'Planned') {
        return (
            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-sky-500/10 text-sky-300 border border-sky-500/20">
                PLAN
            </span>
        );
    }
    if (status === 'Exited') {
        return (
            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-700/25 text-slate-400 border border-white/[0.08]">
                EXIT
            </span>
        );
    }
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

// ─── Stat Card (for Book Analytics) ──────────────────────────
const StatCard = ({ icon, label, value, subtext, color, borderColor, bgColor }: {
    icon: React.ReactNode;
    label: string;
    value: string;
    subtext?: string;
    color: string;
    borderColor?: string;
    bgColor?: string;
}) => (
    <div className={cn(
        "relative flex flex-col gap-1.5 rounded-xl px-3.5 py-3 overflow-hidden",
        "border transition-all duration-300 hover:scale-[1.02] hover:shadow-lg",
        borderColor || "border-white/[0.07]",
        bgColor || "bg-white/[0.025]"
    )}>
        {/* Subtle glow accent in top-right */}
        <div className={cn("absolute -top-4 -right-4 w-16 h-16 rounded-full blur-2xl opacity-20", color.replace('text-', 'bg-'))} />
        <div className="flex items-center gap-1.5 relative z-[1]">
            {icon}
            <span className="text-[9px] uppercase tracking-[0.14em] text-gray-500 font-semibold">{label}</span>
        </div>
        <span className={cn("font-mono text-xl font-black leading-none tracking-tight relative z-[1]", color)}>
            {value}
        </span>
        {subtext && (
            <span className="text-[9px] text-gray-500 leading-tight relative z-[1]">{subtext}</span>
        )}
    </div>
);

// ─── Column Group Definitions ────────────────────────────────
interface ColumnDef {
    key: SortKey;
    label: string;
    tooltip?: string;
    group: ColumnGroup;
}

const columns: ColumnDef[] = [
    { key: 'ticker',           label: 'Ticker',     group: 'position' },
    { key: 'lastPrice',        label: 'Price',      group: 'position', tooltip: 'Last fetched price' },
    { key: 'currentWeight',    label: 'Weight',     group: 'position', tooltip: 'Cost-aware drifted weight as a share of estimated net NAV' },
    { key: 'ytdContribution',  label: 'YTD Gross',  group: 'contribution', tooltip: 'Gross security contribution before financing, including prior books and exited/rebalanced exposure' },
    { key: 'sinceRebalanceContribution', label: '2H 2026', group: 'contribution', tooltip: 'Second-half 2026 contribution on the same YTD basis as YTD Total' },
    { key: 'r7dContribution',  label: '7D',         group: 'contribution', tooltip: '7-day portfolio contribution' },
    { key: 'r1dContribution',  label: '1D',         group: 'contribution', tooltip: '1-day portfolio contribution' },
    { key: 'r1d',              label: '1D',         group: 'returns', tooltip: '1-day return' },
    { key: 'ytd',              label: 'YTD',        group: 'returns' },
    { key: 'r7d',              label: '7D',         group: 'returns', tooltip: '7-day return' },
    { key: 'r1m',              label: '1M',         group: 'returns' },
    { key: 'volatility',       label: 'Vol',        group: 'risk', tooltip: 'Annualized volatility' },
    { key: 'volatilityContribution', label: 'Vol Contrib. %', group: 'risk', tooltip: 'Volatility contribution to portfolio (% of total portfolio vol)' },
    { key: 'volumeIndicator',  label: 'Vol Ratio',  group: 'risk', tooltip: '7D avg volume ÷ YTD avg volume' },
];

const columnByKey = new Map<SortKey, ColumnDef>(columns.map(col => [col.key, col]));
const defaultColumnOrder = columns.map(col => col.key);
const columnOrderStorageKey = 'returnsHeatmap.columnOrder.v2';

const normalizeColumnOrder = (order: unknown): SortKey[] => {
    const validKeys = new Set(defaultColumnOrder);
    const ordered = Array.isArray(order)
        ? order.filter((key): key is SortKey => typeof key === 'string' && validKeys.has(key as SortKey))
        : [];
    const missing = defaultColumnOrder.filter(key => !ordered.includes(key));
    return [...ordered, ...missing];
};

const getInitialColumnOrder = (): SortKey[] => {
    if (typeof window === 'undefined') return defaultColumnOrder;
    try {
        return normalizeColumnOrder(JSON.parse(window.localStorage.getItem(columnOrderStorageKey) || 'null'));
    } catch {
        return defaultColumnOrder;
    }
};

const groupMeta: Record<ColumnGroup, { label: string; icon: React.ReactNode; color: string; accentColor: string }> = {
    position:     { label: 'Position',      icon: <BarChart3 className="h-3 w-3" />, color: 'text-blue-400',    accentColor: 'bg-blue-500' },
    contribution: { label: 'Contribution',  icon: <Zap className="h-3 w-3" />,       color: 'text-violet-400',  accentColor: 'bg-violet-500' },
    returns:      { label: 'Returns',       icon: <TrendingUp className="h-3 w-3" />,color: 'text-emerald-400', accentColor: 'bg-emerald-500' },
    risk:         { label: 'Risk',          icon: <Flame className="h-3 w-3" />,     color: 'text-rose-400',    accentColor: 'bg-rose-500' },
};

// ─── Main Component ──────────────────────────────────────────
export const ReturnsHeatmap = React.memo(({ periodicReturns, activeRisks = [], periodLabel = "YTD", vitals }: {
    periodicReturns: PeriodicReturn[];
    activeRisks?: RiskAttribution[];
    periodLabel?: string;
    vitals?: Pick<Vitals, 'ytdReturn' | 'ytdReturnGross' | 'ytdSecurityGrossContribution' | 'ytdFinancingCost' | 'financingScope'>;
}) => {
    const [sortKey, setSortKey] = useState<SortKey>('ytdContribution');
    const [sortDir, setSortDir] = useState<SortDir>('desc');
    const [hoveredRow, setHoveredRow] = useState<string | null>(null);
    const [columnOrder, setColumnOrder] = useState<SortKey[]>(getInitialColumnOrder);
    const [draggedColumn, setDraggedColumn] = useState<SortKey | null>(null);
    const [dragOverColumn, setDragOverColumn] = useState<SortKey | null>(null);
    const skipNextSortRef = useRef(false);
    const pointerDragColumnRef = useRef<SortKey | null>(null);
    const pointerStartRef = useRef<{ x: number; y: number } | null>(null);

    const orderedColumns = useMemo(() => {
        return normalizeColumnOrder(columnOrder)
            .map(key => columnByKey.get(key))
            .filter((col): col is ColumnDef => Boolean(col));
    }, [columnOrder]);

    const groupedColumnSegments = useMemo(() => {
        const segments: Array<{ group: ColumnGroup; colSpan: number }> = [];
        for (const col of orderedColumns) {
            const last = segments[segments.length - 1];
            if (last?.group === col.group) {
                last.colSpan += 1;
            } else {
                segments.push({ group: col.group, colSpan: 1 });
            }
        }
        return segments;
    }, [orderedColumns]);

    const commitColumnOrder = useCallback((nextOrder: SortKey[]) => {
        const normalized = normalizeColumnOrder(nextOrder);
        setColumnOrder(normalized);
        if (typeof window !== 'undefined') {
            window.localStorage.setItem(columnOrderStorageKey, JSON.stringify(normalized));
        }
    }, []);

    const moveColumn = useCallback((sourceKey: SortKey, targetKey: SortKey) => {
        if (sourceKey === targetKey) return;
        const current = normalizeColumnOrder(columnOrder);
        const withoutSource = current.filter(key => key !== sourceKey);
        const targetIndex = withoutSource.indexOf(targetKey);
        if (targetIndex === -1) return;
        withoutSource.splice(targetIndex, 0, sourceKey);
        commitColumnOrder(withoutSource);
    }, [columnOrder, commitColumnOrder]);

    const resetColumnOrder = useCallback(() => {
        commitColumnOrder(defaultColumnOrder);
        setDraggedColumn(null);
        setDragOverColumn(null);
    }, [commitColumnOrder]);

    const riskMap = useMemo(() => {
        const map = new Map<string, number>();
        for (const r of activeRisks) {
            map.set(r.ticker, r.pctRisk);
        }
        return map;
    }, [activeRisks]);

    const handleSort = (key: SortKey) => {
        if (skipNextSortRef.current) {
            skipNextSortRef.current = false;
            return;
        }
        if (sortKey === key) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
        } else {
            setSortKey(key);
            setSortDir('desc');
        }
    };

    const clearColumnDrag = () => {
        setDraggedColumn(null);
        setDragOverColumn(null);
        pointerDragColumnRef.current = null;
        pointerStartRef.current = null;
        window.setTimeout(() => {
            skipNextSortRef.current = false;
        }, 0);
    };

    const handleColumnPointerDown = (key: SortKey, event: React.PointerEvent<HTMLTableCellElement>) => {
        pointerDragColumnRef.current = key;
        pointerStartRef.current = { x: event.clientX, y: event.clientY };
    };

    const handleColumnPointerMove = (key: SortKey, event: React.PointerEvent<HTMLTableCellElement>) => {
        const sourceKey = pointerDragColumnRef.current;
        const start = pointerStartRef.current;
        if (!sourceKey || !start) return;

        const moved = Math.abs(event.clientX - start.x) > 8 || Math.abs(event.clientY - start.y) > 8;
        if (!moved) return;

        skipNextSortRef.current = true;
        setDraggedColumn(sourceKey);
        setDragOverColumn(key);
    };

    const handleColumnPointerEnter = (key: SortKey) => {
        if (draggedColumn) setDragOverColumn(key);
    };

    const handleColumnPointerUp = (key: SortKey, event: React.PointerEvent<HTMLTableCellElement>) => {
        const sourceKey = pointerDragColumnRef.current;
        if (sourceKey && draggedColumn) {
            event.preventDefault();
            event.stopPropagation();
            moveColumn(sourceKey, dragOverColumn ?? key);
        }
        clearColumnDrag();
    };

    const getValue = useCallback((row: PeriodicReturn, key: SortKey): number | null => {
        switch (key) {
            case 'ticker': return null;
            case 'ytd': return row.ytd ?? null;
            case 'ytdContribution': return row.ytdContribution ?? null;
            case 'sinceRebalanceContribution': return getSinceRebalanceDisplayContribution(row);
            case 'r7dContribution': return row.r7dContribution ?? null;
            case 'r1dContribution': return row.r1dContribution ?? null;
            case 'r1d': return row.r1d ?? null;
            case 'r7d': return row.r7d ?? null;
            case 'r1m': return row.r1m ?? null;
            case 'r1y': return row.r1y ?? null;
            case 'lastPrice': return row.lastPrice ?? null;
            case 'volatility': return row.volatility ?? null;
            case 'volatilityContribution': return riskMap.get(row.ticker) ?? null;
            case 'volumeIndicator': return row.volumeIndicator ?? null;
            case 'currentWeight': return row.currentWeight ?? null;
            case 'entryPrice': return row.entryPrice ?? null;
            case 'rSinceEntry': return (row.lastPrice && row.entryPrice) ? ((row.lastPrice - row.entryPrice) / row.entryPrice) : null;
            default: return null;
        }
    }, [riskMap]);

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
    }, [getValue, periodicReturns, sortKey, sortDir]);

    // Compute max absolute contribution for bar scaling
    const maxAbsContrib = useMemo(() => {
        let max = 0;
        for (const r of periodicReturns) {
            if (r.ytdContribution !== null && r.ytdContribution !== undefined) max = Math.max(max, Math.abs(r.ytdContribution));
            const sinceRebalance = getSinceRebalanceDisplayContribution(r);
            if (sinceRebalance !== null) max = Math.max(max, Math.abs(sinceRebalance));
            if (r.r7dContribution !== null && r.r7dContribution !== undefined) max = Math.max(max, Math.abs(r.r7dContribution));
            if (r.r1dContribution !== null && r.r1dContribution !== undefined) max = Math.max(max, Math.abs(r.r1dContribution));
        }
        return max || 0.01;
    }, [periodicReturns]);

    const summary = useMemo(() => {
        let ytdC = 0, sinceRebalanceC = 0, r7dC = 0, r1dC = 0;
        let longCount = 0, shortCount = 0;
        for (const r of periodicReturns) {
            if (r.ytdContribution != null) ytdC += r.ytdContribution;
            const sinceRebalance = getSinceRebalanceDisplayContribution(r);
            if (sinceRebalance != null) sinceRebalanceC += sinceRebalance;
            if (r.r7dContribution != null) r7dC += r.r7dContribution;
            if (r.r1dContribution != null) r1dC += r.r1dContribution;
            if ((r.status === undefined || r.status === 'Active') && r.direction === 'Long') longCount++;
            if ((r.status === undefined || r.status === 'Active') && r.direction === 'Short') shortCount++;
        }
        return { ytdC, sinceRebalanceC, r7dC, r1dC, longCount, shortCount, total: longCount + shortCount };
    }, [periodicReturns]);

    const reconciliation = useMemo(() => {
        if (!vitals) return null;
        const grossSecurity = vitals.ytdSecurityGrossContribution ?? vitals.ytdReturnGross ?? summary.ytdC;
        const financingImpact = vitals.ytdFinancingCost ?? 0;
        const netReturn = vitals.ytdReturn;
        return {
            grossSecurity,
            financingImpact,
            netReturn,
            residual: grossSecurity - financingImpact - netReturn,
        };
    }, [summary.ytdC, vitals]);

    // Book Analytics — hedge fund standard metrics
    const bookAnalytics = useMemo(() => {
        // Filter to actual portfolio positions (have a contribution)
        const positions = periodicReturns.filter(r => r.ytdContribution != null && r.direction);
        if (positions.length === 0) return null;

        const winners = positions.filter(r => r.ytdContribution! > 0);
        const losers = positions.filter(r => r.ytdContribution! < 0);

        // Batting Average: % of positions that are profitable
        const battingAvg = positions.length > 0 ? winners.length / positions.length : 0;

        // Profit Factor: Σ(gains) / |Σ(losses)|
        const totalGains = winners.reduce((s, r) => s + r.ytdContribution!, 0);
        const totalLosses = Math.abs(losers.reduce((s, r) => s + r.ytdContribution!, 0));
        const profitFactor = totalLosses > 0 ? totalGains / totalLosses : totalGains > 0 ? Infinity : 0;

        // Win/Loss Ratio: avg gain on winners / |avg loss on losers|
        const avgWin = winners.length > 0 ? totalGains / winners.length : 0;
        const avgLoss = losers.length > 0 ? totalLosses / losers.length : 0;
        const winLossRatio = avgLoss > 0 ? avgWin / avgLoss : avgWin > 0 ? Infinity : 0;

        // Best & Worst contributor
        const sorted = [...positions].sort((a, b) => (b.ytdContribution ?? 0) - (a.ytdContribution ?? 0));
        const best = sorted[0];
        const worst = sorted[sorted.length - 1];

        // Top-5 concentration uses gross current exposure: longs and shorts both consume risk budget.
        const withWeights = positions.filter(r => r.currentWeight != null);
        const exposureWeight = (row: PeriodicReturn) => Math.abs(row.currentWeight ?? 0);
        const sortedByWeight = [...withWeights].sort((a, b) => exposureWeight(b) - exposureWeight(a));
        const top5GrossWeight = sortedByWeight.slice(0, 5).reduce((s, r) => s + exposureWeight(r), 0);
        const totalGrossWeight = withWeights.reduce((s, r) => s + exposureWeight(r), 0);
        const top5GrossShare = totalGrossWeight > 0 ? top5GrossWeight / totalGrossWeight : 0;

        return {
            battingAvg,
            profitFactor,
            winLossRatio,
            best: best ? { ticker: best.ticker, value: best.ytdContribution! } : null,
            worst: worst ? { ticker: worst.ticker, value: worst.ytdContribution! } : null,
            top5GrossWeight,
            top5GrossShare,
            totalGrossWeight,
            winnersCount: winners.length,
            losersCount: losers.length,
        };
    }, [periodicReturns]);

    const SortIndicator = ({ columnKey }: { columnKey: SortKey }) => {
        if (sortKey !== columnKey) {
            return <span className="inline-block ml-0.5 opacity-0 group-hover:opacity-30 transition-opacity"><ChevronDown className="h-3 w-3 inline" /></span>;
        }
        return sortDir === 'desc'
            ? <ChevronDown className="h-3 w-3 inline ml-0.5 text-blue-400" />
            : <ChevronUp className="h-3 w-3 inline ml-0.5 text-blue-400" />;
    };

    const renderCell = (row: PeriodicReturn, col: ColumnDef, isFirstInGroup: boolean, isFirstColumn: boolean) => {
        const isHovered = hoveredRow === row.ticker;
        // Contribution and Returns both contain a "1D" and a "7D" column, rendered side by
        // side. The group divider is the only thing distinguishing them, so it has to be seen.
        const groupBorder = isFirstInGroup && col.group !== 'position' ? "border-l border-white/[0.12]" : "";
        const isStickyTicker = col.key === 'ticker' && isFirstColumn;

        switch (col.key) {
            case 'ticker':
                return (
                    <td key={col.key} className={cn(
                        "px-4 py-3 whitespace-nowrap",
                        isStickyTicker && [
                            "sticky left-0 z-[5] bg-slate-950/95 backdrop-blur-sm",
                            // right shadow for sticky column
                            "after:absolute after:top-0 after:right-0 after:bottom-0 after:w-[1px] after:bg-gradient-to-b after:from-white/[0.06] after:via-white/[0.03] after:to-white/[0.06]",
                        ],
                        groupBorder
                    )}>
                        <div className="flex items-center gap-2.5">
                            <span className={cn(
                                "font-semibold text-[13px] tracking-wide transition-colors duration-150",
                                isHovered ? "text-white" : "text-gray-200"
                            )}>
                                {row.ticker}
                            </span>
                            <DirectionBadge direction={row.direction} status={row.status} />
                        </div>
                    </td>
                );
            case 'lastPrice':
            case 'entryPrice': {
                const val = col.key === 'lastPrice' ? row.lastPrice : row.entryPrice;
                return (
                    <td key={col.key} className={cn("px-4 py-3 text-right font-mono text-[13px] whitespace-nowrap", val ? "text-gray-300" : "text-gray-600", groupBorder)}>
                        {formatPrice(val ?? null, row.currency)}
                    </td>
                );
            }
            case 'currentWeight':
                return (
                    <td key={col.key} className={cn("px-4 py-3", groupBorder)}>
                        <WeightBar current={row.currentWeight} initial={row.weight} />
                    </td>
                );
            case 'ytdContribution':
            case 'sinceRebalanceContribution':
            case 'r7dContribution':
            case 'r1dContribution': {
                const val = col.key === 'ytdContribution' ? row.ytdContribution :
                            col.key === 'sinceRebalanceContribution' ? getSinceRebalanceDisplayContribution(row) :
                            col.key === 'r7dContribution' ? row.r7dContribution : row.r1dContribution;
                const normalizedVal = val ?? null;
                const title = col.key === 'sinceRebalanceContribution' && row.sinceRebalanceStartDate
                    ? `2H 2026 contribution from ${row.sinceRebalanceStartDate}; same YTD basis as YTD Total`
                    : col.tooltip;
                return (
                    <td key={col.key} className={cn(
                        "px-4 py-3 text-center font-mono text-[13px] relative transition-all duration-200",
                        getContribColor(normalizedVal),
                        isHovered && "brightness-125",
                        groupBorder
                    )}
                    title={title}
                    >
                        <span className="relative z-[1]">{formatContribution(normalizedVal)}</span>
                        <ContribBar value={normalizedVal} maxAbsValue={maxAbsContrib} />
                    </td>
                );
            }
            case 'ytd':
            case 'r7d':
            case 'r1m':
            case 'r1y':
            case 'r1d':
            case 'rSinceEntry': {
                const val = col.key === 'ytd' ? row.ytd :
                            col.key === 'rSinceEntry' ? ((row.lastPrice && row.entryPrice) ? (row.lastPrice - row.entryPrice) / row.entryPrice : null) :
                            row[col.key as 'r7d' | 'r1m' | 'r1y' | 'r1d'];
                return (
                    <td key={col.key} className={cn(
                        "px-4 py-3 text-center font-mono text-[13px] transition-all duration-200",
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
                        "px-4 py-3 text-center font-mono text-[13px] transition-all duration-200",
                        getVolatilityColor(row.volatility),
                        isHovered && "brightness-125",
                        groupBorder
                    )}>
                        {formatVolatility(row.volatility)}
                    </td>
                );
            case 'volatilityContribution': {
                const val = riskMap.get(row.ticker) ?? null;
                return (
                    <td key={col.key} className={cn(
                        "px-4 py-3 text-center font-mono text-[13px] transition-all duration-200",
                        getRiskContribColor(val),
                        isHovered && "brightness-125",
                        groupBorder
                    )}>
                        {formatRiskContrib(val)}
                    </td>
                );
            }
            case 'volumeIndicator':
                return (
                    <td key={col.key} className={cn(
                        "px-4 py-3 text-center font-mono text-[13px] transition-all duration-200",
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
                return <td key={col.key} className="px-4 py-3 text-gray-600">—</td>;
        }
    };

    return (
        <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-slate-900/80 to-slate-950/90 backdrop-blur-xl shadow-2xl shadow-black/40 overflow-hidden">
            {/* ── Header Bar ────────────────────────────────── */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] bg-white/[0.02]">
                <div className="flex items-center gap-3.5">
                    <div className="relative flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10">
                        <BarChart3 className="h-[18px] w-[18px] text-blue-400" />
                        {/* Breathing glow */}
                        <div className="absolute inset-0 rounded-xl bg-blue-400/10 animate-pulse" />
                    </div>
                    <div>
                        <h3 className="text-[16px] font-bold text-white tracking-tight">Returns Heatmap</h3>
                        <p className="text-[11px] text-gray-500 mt-0.5">Gross security attribution with net-return reconciliation</p>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    {/* Quick stats pills */}
                    <div className="hidden sm:flex items-center gap-2">
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-[11px] font-mono text-emerald-400 transition-colors hover:bg-emerald-500/15">
                            <ArrowUpRight className="h-3 w-3" /> {summary.longCount} longs
                        </span>
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-rose-500/10 border border-rose-500/20 text-[11px] font-mono text-rose-400 transition-colors hover:bg-rose-500/15">
                            <ArrowDownRight className="h-3 w-3" /> {summary.shortCount} shorts
                        </span>
                    </div>
                    <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.06]">
                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        <span className="text-[11px] text-gray-400 font-mono">{summary.total} positions</span>
                    </div>
                    <button
                        type="button"
                        onClick={resetColumnOrder}
                        title="Reset column order"
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.06] bg-white/[0.035] text-gray-500 transition-colors hover:border-white/[0.12] hover:bg-white/[0.07] hover:text-gray-300"
                    >
                        <RotateCcw className="h-3.5 w-3.5" />
                    </button>
                </div>
            </div>

            {/* ── Summary Strip ─────────────────────────────── */}
            <div className="grid grid-cols-2 lg:grid-cols-4 border-b border-white/[0.06]">
                {[
                    { label: `${periodLabel} Security Gross`, value: summary.ytdC, icon: <TrendingUp className="h-4 w-4" />, gradient: 'from-blue-500/10 to-transparent' },
                    { label: '2H 2026', value: summary.sinceRebalanceC, icon: <Target className="h-4 w-4" />, gradient: 'from-sky-500/10 to-transparent' },
                    { label: '7D Impact', value: summary.r7dC, icon: <Zap className="h-4 w-4" />, gradient: 'from-violet-500/10 to-transparent' },
                    { label: '1D Impact', value: summary.r1dC, icon: <Flame className="h-4 w-4" />, gradient: 'from-orange-500/10 to-transparent' },
                ].map((item, index) => (
                    <div key={item.label} className={cn(
                        "relative flex items-center justify-center gap-3 px-5 py-3.5 overflow-hidden",
                        "transition-colors duration-300 hover:bg-white/[0.02]",
                        index % 2 === 1 && "border-l border-white/[0.06]",
                        index < 2 && "border-b border-white/[0.06] lg:border-b-0",
                        index > 0 && "lg:border-l lg:border-white/[0.06]"
                    )}>
                        {/* Subtle background gradient */}
                        <div className={cn("absolute inset-0 bg-gradient-to-r opacity-50", item.gradient)} />
                        <span className={cn(
                            "relative p-1.5 rounded-lg",
                            item.value >= 0
                                ? "text-emerald-400 bg-emerald-500/10 ring-1 ring-emerald-500/20"
                                : "text-red-400 bg-red-500/10 ring-1 ring-red-500/20"
                        )}>
                            {item.icon}
                        </span>
                        <div className="flex flex-col relative">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">{item.label}</span>
                            <span className={cn(
                                "font-mono text-[15px] font-black tracking-tight leading-tight",
                                item.value > 0 ? "text-emerald-400" : item.value < 0 ? "text-red-400" : "text-gray-400"
                            )}>
                                {item.value > 0 ? '+' : ''}{(item.value * 100).toFixed(2)}%
                            </span>
                        </div>
                    </div>
                ))}
            </div>

            {/* ── Book Analytics Strip ──────────────────────── */}
            {reconciliation && (
                <div className="border-b border-white/[0.06] bg-slate-950/35 px-4 py-3 sm:px-6">
                    <div className="grid grid-cols-1 divide-y divide-white/[0.06] rounded-lg border border-white/[0.06] bg-white/[0.02] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
                        <div className="flex items-center justify-between gap-3 px-3.5 py-3 sm:px-4">
                            <div className="flex min-w-0 items-center gap-2">
                                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-sky-500/10 text-sky-300">
                                    <TrendingUp className="h-3.5 w-3.5" />
                                </span>
                                <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-400">Security gross</span>
                            </div>
                            <span className={cn("font-mono text-sm font-black tabular-nums", reconciliation.grossSecurity >= 0 ? "text-emerald-400" : "text-rose-400")}>
                                {formatContribution(reconciliation.grossSecurity)}
                            </span>
                        </div>
                        <div className="flex items-center justify-between gap-3 px-3.5 py-3 sm:px-4" title={vitals?.financingScope}>
                            <div className="flex min-w-0 items-center gap-2">
                                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-rose-500/10 text-rose-300">
                                    <TrendingDown className="h-3.5 w-3.5" />
                                </span>
                                <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-400">Estimated carry</span>
                            </div>
                            <span className="font-mono text-sm font-black tabular-nums text-rose-400">
                                {formatContribution(-reconciliation.financingImpact)}
                            </span>
                        </div>
                        <div className="flex items-center justify-between gap-3 px-3.5 py-3 sm:px-4">
                            <div className="flex min-w-0 items-center gap-2">
                                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-300">
                                    <Target className="h-3.5 w-3.5" />
                                </span>
                                <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-400">Net realised</span>
                            </div>
                            <span className={cn("font-mono text-sm font-black tabular-nums", reconciliation.netReturn >= 0 ? "text-emerald-400" : "text-rose-400")}>
                                {formatContribution(reconciliation.netReturn)}
                            </span>
                        </div>
                    </div>
                    {Math.abs(reconciliation.residual) > 0.0001 && (
                        <p className="mt-2 text-[10px] text-amber-400">Reconciliation variance {formatContribution(reconciliation.residual)}</p>
                    )}
                </div>
            )}

            {bookAnalytics && (
                <div className="border-b border-white/[0.06] bg-gradient-to-r from-white/[0.01] via-white/[0.03] to-white/[0.01] px-6 py-4">
                    <div className="flex items-center gap-2 mb-3">
                        <div className="flex items-center justify-center w-5 h-5 rounded-md bg-indigo-500/15 ring-1 ring-indigo-500/20">
                            <Activity className="h-3 w-3 text-indigo-400" />
                        </div>
                        <span className="text-[10px] uppercase tracking-[0.16em] font-bold text-gray-400">Book Analytics</span>
                        <div className="flex-1 h-px bg-gradient-to-r from-white/[0.06] to-transparent ml-2" />
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                        <StatCard
                            icon={<Target className="h-3.5 w-3.5 text-indigo-400" />}
                            label="Batting Avg"
                            value={`${(bookAnalytics.battingAvg * 100).toFixed(0)}%`}
                            subtext={`${bookAnalytics.winnersCount}W / ${bookAnalytics.losersCount}L`}
                            color={bookAnalytics.battingAvg >= 0.55 ? "text-emerald-400" : bookAnalytics.battingAvg >= 0.45 ? "text-amber-400" : "text-red-400"}
                        />
                        <StatCard
                            icon={<Zap className="h-3.5 w-3.5 text-amber-400" />}
                            label="Profit Factor"
                            value={bookAnalytics.profitFactor === Infinity ? '∞' : `${bookAnalytics.profitFactor.toFixed(2)}×`}
                            subtext="gains / losses"
                            color={bookAnalytics.profitFactor >= 2.0 ? "text-emerald-400" : bookAnalytics.profitFactor >= 1.0 ? "text-amber-400" : "text-red-400"}
                        />
                        <StatCard
                            icon={<BarChart3 className="h-3.5 w-3.5 text-sky-400" />}
                            label="Win / Loss"
                            value={bookAnalytics.winLossRatio === Infinity ? '∞' : `${bookAnalytics.winLossRatio.toFixed(2)}×`}
                            subtext="avg winner / avg loser"
                            color={bookAnalytics.winLossRatio >= 1.5 ? "text-emerald-400" : bookAnalytics.winLossRatio >= 1.0 ? "text-amber-400" : "text-red-400"}
                        />
                        <StatCard
                            icon={<Flame className="h-3.5 w-3.5 text-orange-400" />}
                            label="Top 5 Gross"
                            value={`${(bookAnalytics.top5GrossWeight * 100).toFixed(0)}%`}
                            subtext={`${(bookAnalytics.top5GrossShare * 100).toFixed(0)}% of ${(bookAnalytics.totalGrossWeight * 100).toFixed(0)}% gross`}
                            color={bookAnalytics.top5GrossWeight >= 1.0 || bookAnalytics.top5GrossShare >= 0.75 ? "text-rose-400" : bookAnalytics.top5GrossWeight >= 0.75 || bookAnalytics.top5GrossShare >= 0.55 ? "text-amber-400" : "text-emerald-400"}
                        />
                        {bookAnalytics.best && (
                            <StatCard
                                icon={<Trophy className="h-3.5 w-3.5 text-emerald-400" />}
                                label="Best"
                                value={bookAnalytics.best.ticker}
                                subtext={`+${(bookAnalytics.best.value * 100).toFixed(2)}% contrib`}
                                color="text-emerald-400"
                                borderColor="border-emerald-500/15"
                                bgColor="bg-emerald-500/[0.04]"
                            />
                        )}
                        {bookAnalytics.worst && bookAnalytics.worst.value < 0 && (
                            <StatCard
                                icon={<TrendingDown className="h-3.5 w-3.5 text-rose-400" />}
                                label="Worst"
                                value={bookAnalytics.worst.ticker}
                                subtext={`${(bookAnalytics.worst.value * 100).toFixed(2)}% contrib`}
                                color="text-rose-400"
                                borderColor="border-rose-500/15"
                                bgColor="bg-rose-500/[0.04]"
                            />
                        )}
                    </div>
                </div>
            )}

            {/* ── Table ─────────────────────────────────────── */}
            <div className="overflow-x-auto max-h-[560px] overflow-y-auto scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
                <table className="w-full text-sm border-collapse">
                    {/* Group Header Row */}
                    <thead className="sticky top-0 z-20">
                        <tr className="bg-slate-950/98 backdrop-blur-md">
                            {groupedColumnSegments.map((segment, groupIdx) => {
                                const meta = groupMeta[segment.group];
                                return (
                                <th
                                    key={`${segment.group}-${groupIdx}`}
                                    colSpan={segment.colSpan}
                                    className={cn(
                                        "px-4 py-2 text-[10px] uppercase tracking-[0.14em] font-semibold",
                                        groupIdx > 0 && "border-l border-white/[0.12]",
                                        segment.group === 'position' && "text-left"
                                    )}
                                >
                                    <div className={cn(
                                        "flex items-center gap-2",
                                        segment.group !== 'position' && "justify-center"
                                    )}>
                                        <div className={cn(
                                            "flex items-center gap-1.5 px-2 py-0.5 rounded-md",
                                            "bg-white/[0.03] border border-white/[0.06]",
                                            meta.color
                                        )}>
                                            {meta.icon}
                                            <span className="text-gray-400">{meta.label}</span>
                                        </div>
                                        {/* Accent line */}
                                        <div className={cn("hidden sm:block flex-1 h-[1px] rounded-full opacity-40", meta.accentColor)} />
                                    </div>
                                </th>
                                );
                            })}
                        </tr>
                        {/* Column Header Row */}
                        <tr className="bg-slate-950/95 backdrop-blur-md border-b border-white/[0.08]">
                            {orderedColumns.map((col, i) => {
                                const isFirstInGroup = i === 0 || orderedColumns[i - 1].group !== col.group;
                                const isFirstColumn = i === 0;
                                const isDragging = draggedColumn === col.key;
                                const isDropTarget = dragOverColumn === col.key && draggedColumn !== null && draggedColumn !== col.key;
                                return (
                                    <th
                                        key={col.key}
                                        data-column-key={col.key}
                                        tabIndex={0}
                                        aria-sort={sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                                        onClick={() => handleSort(col.key)}
                                        // Enter only. Space would hijack page-down scrolling once a
                                        // header has focus, and this page is very long.
                                        onKeyDown={(event) => {
                                            if (event.key === 'Enter') {
                                                event.preventDefault();
                                                handleSort(col.key);
                                            }
                                        }}
                                        onPointerDown={(event) => handleColumnPointerDown(col.key, event)}
                                        onPointerMove={(event) => handleColumnPointerMove(col.key, event)}
                                        onPointerEnter={() => handleColumnPointerEnter(col.key)}
                                        onPointerUp={(event) => handleColumnPointerUp(col.key, event)}
                                        onPointerCancel={clearColumnDrag}
                                        title={col.tooltip}
                                        className={cn(
                                            "group px-4 py-2.5 font-medium cursor-grab select-none whitespace-nowrap transition-all duration-150 active:cursor-grabbing",
                                            "hover:bg-white/[0.04] active:bg-white/[0.08]",
                                            "outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-blue-400/70",
                                            col.key === 'ticker' && isFirstColumn ? "text-left text-gray-300 sticky left-0 z-[15] bg-slate-950/95" : col.key === 'ticker' ? "text-left text-gray-300" : "text-center text-gray-400",
                                            sortKey === col.key && "text-blue-400 bg-blue-500/[0.06]",
                                            isFirstInGroup && col.group !== 'position' && "border-l border-white/[0.12]",
                                            isDragging && "opacity-50",
                                            isDropTarget && "bg-blue-500/[0.12] shadow-[inset_2px_0_0_rgba(96,165,250,0.75)]",
                                            "text-[12px]"
                                        )}
                                    >
                                        <div className={cn(
                                            "flex items-center gap-1.5",
                                            col.key === 'ticker' ? "justify-start" : "justify-center"
                                        )}>
                                            <GripVertical className={cn(
                                                "h-3 w-3 shrink-0 text-gray-600 transition-colors",
                                                isDragging ? "text-blue-300" : "group-hover:text-gray-400"
                                            )} />
                                            <span>{col.label === 'YTD' ? periodLabel : col.label}</span>
                                            <SortIndicator columnKey={col.key} />
                                        </div>
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
                                    "relative transition-all duration-150 border-b border-white/[0.03]",
                                    hoveredRow === row.ticker
                                        ? "bg-white/[0.06] shadow-[inset_3px_0_0_0] shadow-blue-500/60"
                                        : idx % 2 === 0 ? "bg-white/[0.015]" : "bg-transparent"
                                )}
                            >
                                {orderedColumns.map((col, i) => {
                                    const isFirstInGroup = i === 0 || orderedColumns[i - 1].group !== col.group;
                                    return renderCell(row, col, isFirstInGroup, i === 0);
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* ── Footer Legend ──────────────────────────────── */}
            <div className="flex items-center justify-between px-6 py-3 border-t border-white/[0.06] bg-white/[0.015]">
                <div className="flex items-center gap-5 text-[10px] text-gray-500">
                    <span className="flex items-center gap-2">
                        <span className="w-6 h-2.5 rounded-sm bg-gradient-to-r from-red-900/90 via-red-800/70 to-red-700/50 ring-1 ring-red-500/20" />
                        Loss
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-6 h-2.5 rounded-sm bg-gradient-to-r from-gray-700/30 via-gray-600/20 to-gray-700/30 ring-1 ring-white/[0.06]" />
                        Flat
                    </span>
                    <span className="flex items-center gap-2">
                        <span className="w-6 h-2.5 rounded-sm bg-gradient-to-r from-emerald-700/50 via-emerald-800/70 to-emerald-900/90 ring-1 ring-emerald-500/20" />
                        Gain
                    </span>
                </div>
                <div className="flex items-center gap-1.5 text-[10px] text-gray-600">
                    <span className="hidden sm:inline text-gray-700">⌘</span>
                    <span className="font-mono">Click headers to sort</span>
                </div>
            </div>
        </div>
    );
});
