import { useState, useEffect, useCallback } from 'react';
import { cn } from '../../lib/utils';
import {
    TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight,
    AlertTriangle, CheckCircle2, RefreshCw, Loader2,
    Shield, Zap, BarChart3, Target, Brain
} from 'lucide-react';

// ─── Types ────────────────────────────────────────────────────
interface QualityPosition {
    ticker: string;
    direction: 'Long' | 'Short';
    weight: number;
    sector: string;
    name: string;
    grossMargin: number | null;
    roic: number | null;
    roe: number | null;
    debtEquity: number | null;
    revenueGrowth: number | null;
    opMargin: number | null;
    pe: number | null;
    fcfEvYield: number | null;
    ownerEarningsYield: number | null;
    qualityScore: number | null;
    qualityFlags: string[];
    inversionRisks: string[];
    error?: string;
}

interface QualityResponse {
    portfolio: string;
    positions: QualityPosition[];
}

// ─── Helpers ──────────────────────────────────────────────────
const pct = (v: number | null, dec = 1) =>
    v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(dec)}%`;

const fmtX = (v: number | null, dec = 2) =>
    v == null ? '—' : `${v.toFixed(dec)}×`;

const fmtPE = (v: number | null) =>
    v == null ? '—' : v > 0 ? `${v.toFixed(1)}×` : 'N/M';

// Normalize D/E: yfinance sometimes returns it as a percent (e.g. 45.2)
const normDE = (v: number | null) => {
    if (v == null) return null;
    return v > 5 ? v / 100 : v; // assume >5 means it was in % form
};

const scoreColor = (s: number | null) => {
    if (s == null) return 'text-gray-500';
    if (s >= 70)  return 'text-emerald-400';
    if (s >= 45)  return 'text-amber-400';
    if (s >= 20)  return 'text-orange-400';
    return 'text-rose-400';
};

const scoreBg = (s: number | null) => {
    if (s == null) return 'bg-white/5 border-white/10';
    if (s >= 70)  return 'bg-emerald-950/40 border-emerald-500/25';
    if (s >= 45)  return 'bg-amber-950/30 border-amber-500/20';
    if (s >= 20)  return 'bg-orange-950/30 border-orange-500/20';
    return 'bg-rose-950/30 border-rose-500/20';
};

const metricColor = (
    v: number | null,
    good: number,
    bad: number,
    higherIsBetter = true
) => {
    if (v == null) return 'text-gray-600';
    const aboveGood = higherIsBetter ? v >= good : v <= good;
    const aboveBad  = higherIsBetter ? v >= bad  : v <= bad;
    if (aboveGood)  return 'text-emerald-400';
    if (aboveBad)   return 'text-amber-400';
    return 'text-rose-400';
};

// ─── Score Ring ───────────────────────────────────────────────
const ScoreRing = ({ score }: { score: number | null }) => {
    const s = score ?? 0;
    const r = 18;
    const circ = 2 * Math.PI * r;
    const fill = (s / 100) * circ;
    const color = s >= 70 ? '#34d399' : s >= 45 ? '#fbbf24' : s >= 20 ? '#fb923c' : '#f87171';

    return (
        <div className="relative flex items-center justify-center w-12 h-12">
            <svg className="w-12 h-12 -rotate-90" viewBox="0 0 44 44">
                <circle cx="22" cy="22" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="4" />
                <circle
                    cx="22" cy="22" r={r} fill="none"
                    stroke={color} strokeWidth="4"
                    strokeDasharray={`${fill} ${circ - fill}`}
                    strokeLinecap="round"
                    className="transition-all duration-700"
                />
            </svg>
            <span className={cn("absolute text-[11px] font-black", scoreColor(score))}>
                {score ?? '?'}
            </span>
        </div>
    );
};

// ─── Metric Cell ─────────────────────────────────────────────
const MC = ({
    label, value, color, tooltip
}: { label: string; value: string; color: string; tooltip?: string }) => (
    <div className="flex flex-col items-center gap-0.5 min-w-[56px]" title={tooltip}>
        <span className="text-[9px] text-gray-600 uppercase tracking-widest font-medium">{label}</span>
        <span className={cn("font-mono text-[12px] font-bold", color)}>{value}</span>
    </div>
);

// ─── Position Card ────────────────────────────────────────────
const PositionCard = ({ pos }: { pos: QualityPosition }) => {
    const [expanded, setExpanded] = useState(false);
    const isLong = pos.direction === 'Long';
    const de = normDE(pos.debtEquity);

    return (
        <div
            className={cn(
                "rounded-xl border transition-all duration-200 cursor-pointer",
                scoreBg(pos.qualityScore),
                expanded ? "shadow-lg" : "hover:brightness-110"
            )}
            onClick={() => setExpanded(e => !e)}
        >
            {/* Header row */}
            <div className="flex items-center gap-3 px-4 py-3">
                {/* Score ring */}
                <ScoreRing score={pos.qualityScore} />

                {/* Name block */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                        <span className="font-mono text-[13px] font-black text-white">{pos.ticker}</span>
                        {isLong ? (
                            <span className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                                <ArrowUpRight className="h-2.5 w-2.5" /> L
                            </span>
                        ) : (
                            <span className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/20">
                                <ArrowDownRight className="h-2.5 w-2.5" /> S
                            </span>
                        )}
                        <span className="text-[9px] text-gray-600 font-mono">{(pos.weight * 100).toFixed(0)}%</span>
                    </div>
                    <span className="text-[10px] text-gray-500 truncate block">{pos.name}</span>
                </div>

                {/* Quick metric pills */}
                <div className="hidden sm:flex items-center gap-3 shrink-0">
                    <MC
                        label="ROIC"
                        value={pct(pos.roic, 0)}
                        color={metricColor(pos.roic, 0.15, 0.08)}
                        tooltip="Return on Assets (ROIC proxy) — Munger's #1 metric"
                    />
                    <MC
                        label="Grs Mrgn"
                        value={pct(pos.grossMargin, 0)}
                        color={metricColor(pos.grossMargin, 0.50, 0.30)}
                        tooltip="Gross margin — measures pricing power / moat"
                    />
                    <MC
                        label="OE Yield"
                        value={pct(pos.ownerEarningsYield, 1)}
                        color={metricColor(pos.ownerEarningsYield, 0.05, 0.02)}
                        tooltip="Owner Earnings Yield = (FCF − SBC) / EV"
                    />
                    <MC
                        label="D/E"
                        value={de != null ? fmtX(de) : '—'}
                        color={metricColor(de, 0.30, 0.80, false)}
                        tooltip="Debt / Equity — lower is safer (Munger: balance sheet fortress)"
                    />
                </div>

                {/* Expand chevron */}
                <span className="text-gray-600 text-[10px] ml-1">{expanded ? '▲' : '▼'}</span>
            </div>

            {/* Expanded detail */}
            {expanded && (
                <div className="px-4 pb-4 space-y-3 border-t border-white/[0.05]">

                    {/* Metrics grid */}
                    <div className="grid grid-cols-4 sm:grid-cols-6 gap-2 pt-3">
                        <MC label="Op Margin"  value={pct(pos.opMargin, 0)}         color={metricColor(pos.opMargin, 0.20, 0.10)}           tooltip="Operating margin" />
                        <MC label="Rev Growth" value={pct(pos.revenueGrowth, 0)}    color={metricColor(pos.revenueGrowth, 0.10, 0.0)}        tooltip="Trailing 12m revenue growth vs prior year" />
                        <MC label="FCF/EV"     value={pct(pos.fcfEvYield, 1)}       color={metricColor(pos.fcfEvYield, 0.05, 0.02)}          tooltip="Free Cash Flow / Enterprise Value" />
                        <MC label="ROE"        value={pct(pos.roe, 0)}              color={metricColor(pos.roe, 0.20, 0.10)}                 tooltip="Return on Equity" />
                        <MC label="P/E"        value={fmtPE(pos.pe)}               color={pos.pe != null && pos.pe < 20 ? 'text-emerald-400' : pos.pe != null && pos.pe < 35 ? 'text-amber-400' : 'text-rose-400'} tooltip="Trailing P/E" />
                        <MC label="P/B"        value={pos.pe != null ? fmtX(pos.pe) : '—'} color="text-gray-400" tooltip="Price to Book" />
                    </div>

                    {/* Quality flags */}
                    {pos.qualityFlags.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                            {pos.qualityFlags.map((f, i) => (
                                <span
                                    key={i}
                                    className={cn(
                                        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium",
                                        f.startsWith('✓')
                                            ? "bg-emerald-900/40 text-emerald-300 border border-emerald-500/20"
                                            : "bg-rose-900/40 text-rose-300 border border-rose-500/20"
                                    )}
                                >
                                    {f}
                                </span>
                            ))}
                        </div>
                    )}

                    {/* Inversion risks */}
                    <div className="rounded-lg bg-black/20 border border-white/[0.04] px-3 py-2.5">
                        <div className="flex items-center gap-1.5 mb-1.5">
                            <AlertTriangle className="h-3 w-3 text-amber-400" />
                            <span className="text-[10px] text-amber-400/80 uppercase tracking-widest font-semibold">
                                Munger Inversion — What could go wrong?
                            </span>
                        </div>
                        <ul className="space-y-0.5">
                            {pos.inversionRisks.map((r, i) => (
                                <li key={i} className="text-[10px] text-gray-500 flex items-start gap-1.5">
                                    <span className="text-amber-600 mt-0.5 shrink-0">→</span>
                                    {r}
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            )}
        </div>
    );
};

// ─── Concentration Panel ──────────────────────────────────────
const ConcentrationPanel = ({ positions }: { positions: QualityPosition[] }) => {
    const longs   = positions.filter(p => p.direction === 'Long');
    const shorts  = positions.filter(p => p.direction === 'Short');

    const top3Weight = [...longs]
        .sort((a, b) => b.weight - a.weight)
        .slice(0, 3)
        .reduce((s, p) => s + p.weight, 0);

    // Herfindahl-Hirschman Index for longs
    const hhi = longs.reduce((s, p) => {
        const w = p.weight / longs.reduce((t, x) => t + x.weight, 0);
        return s + w * w;
    }, 0);

    const mungerVerdicts = hhi > 0.25
        ? { text: "Highly concentrated — Munger would approve", color: "text-emerald-400" }
        : hhi > 0.15
        ? { text: "Moderate concentration — room to cut", color: "text-amber-400" }
        : { text: "Widely diversified — Munger: 'Diversification is for igno­rance'", color: "text-rose-400" };

    return (
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <Target className="h-3.5 w-3.5 text-amber-400" />
                <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">Concentration · Munger View</span>
            </div>

            <div className="grid grid-cols-3 gap-3">
                <div className="flex flex-col items-center gap-1">
                    <span className="text-[9px] text-gray-600 uppercase tracking-widest">Top 3 Weight</span>
                    <span className="font-mono text-xl font-black text-white">{(top3Weight * 100).toFixed(0)}%</span>
                    <span className="text-[9px] text-gray-600">of total</span>
                </div>
                <div className="flex flex-col items-center gap-1">
                    <span className="text-[9px] text-gray-600 uppercase tracking-widest">HHI (Longs)</span>
                    <span className="font-mono text-xl font-black text-white">{hhi.toFixed(3)}</span>
                    <span className="text-[9px] text-gray-600">0=spread, 1=all-in</span>
                </div>
                <div className="flex flex-col items-center gap-1">
                    <span className="text-[9px] text-gray-600 uppercase tracking-widest">Positions</span>
                    <span className="font-mono text-xl font-black text-white">{longs.length}L / {shorts.length}S</span>
                    <span className="text-[9px] text-gray-600">long / short</span>
                </div>
            </div>

            <div className="rounded-lg bg-amber-950/20 border border-amber-500/15 px-3 py-2">
                <p className={cn("text-[10px] font-semibold", mungerVerdicts.color)}>
                    {mungerVerdicts.text}
                </p>
                <p className="text-[9px] text-gray-600 mt-0.5">
                    "The idea of excessive diversification is madness." — C. Munger
                </p>
            </div>
        </div>
    );
};

// ─── Portfolio Quality Summary ────────────────────────────────
const QualitySummary = ({ positions }: { positions: QualityPosition[] }) => {
    const longs  = positions.filter(p => p.direction === 'Long' && p.qualityScore != null);
    const shorts = positions.filter(p => p.direction === 'Short' && p.qualityScore != null);

    const avgScore = (arr: QualityPosition[]) =>
        arr.length ? arr.reduce((s, p) => s + (p.qualityScore ?? 0), 0) / arr.length : null;

    const avgMetric = (arr: QualityPosition[], key: keyof QualityPosition) => {
        const vals = arr.map(p => p[key] as number | null).filter(v => v != null) as number[];
        return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    };

    const longScore  = avgScore(longs);
    const shortScore = avgScore(shorts);

    return (
        <div className="grid grid-cols-2 gap-3">
            {[
                { label: "Avg Quality · Longs",  score: longScore,  color: "text-emerald-400", positions: longs },
                { label: "Avg Quality · Shorts", score: shortScore, color: "text-rose-400",    positions: shorts },
            ].map(({ label, score, color, positions: ps }) => (
                <div key={label} className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-4">
                    <p className="text-[10px] text-gray-500 uppercase tracking-widest mb-2">{label}</p>
                    <div className="flex items-end gap-3">
                        <span className={cn("font-mono text-3xl font-black", scoreColor(score))}>
                            {score != null ? Math.round(score) : '—'}
                        </span>
                        <span className="text-[9px] text-gray-600 mb-1">/ 100</span>
                    </div>
                    <div className="mt-2 space-y-0.5">
                        <div className="flex justify-between text-[9px]">
                            <span className="text-gray-600">Avg ROIC</span>
                            <span className={metricColor(avgMetric(ps, 'roic'), 0.15, 0.08)}>
                                {pct(avgMetric(ps, 'roic'), 0)}
                            </span>
                        </div>
                        <div className="flex justify-between text-[9px]">
                            <span className="text-gray-600">Avg Gross Margin</span>
                            <span className={metricColor(avgMetric(ps, 'grossMargin'), 0.50, 0.30)}>
                                {pct(avgMetric(ps, 'grossMargin'), 0)}
                            </span>
                        </div>
                        <div className="flex justify-between text-[9px]">
                            <span className="text-gray-600">Avg OE Yield</span>
                            <span className={metricColor(avgMetric(ps, 'ownerEarningsYield'), 0.05, 0.02)}>
                                {pct(avgMetric(ps, 'ownerEarningsYield'), 1)}
                            </span>
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
};

// ─── Main Component ───────────────────────────────────────────
export const MoatWidget = ({ portfolioName = 'main' }: { portfolioName?: string }) => {
    const [data,    setData]    = useState<QualityResponse | null>(null);
    const [loading, setLoading] = useState(false);
    const [error,   setError]   = useState<string | null>(null);
    const [filter,  setFilter]  = useState<'all' | 'Long' | 'Short'>('all');
    const [sort,    setSort]    = useState<'score' | 'weight'>('score');
    const [loaded,  setLoaded]  = useState(false);  // lazy — only fetch when user expands

    const BASE_URL = (import.meta as any).env?.VITE_API_URL || '';

    const fetch_ = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res  = await fetch(`${BASE_URL}/api/quality?portfolio=${portfolioName}`);
            const json = await res.json();
            if (json.error) setError(json.error);
            else { setData(json); setLoaded(true); }
        } catch (e: any) {
            setError('Failed to connect to backend.');
        } finally {
            setLoading(false);
        }
    }, [BASE_URL, portfolioName]);

    // Auto-fetch on mount
    useEffect(() => { fetch_(); }, [fetch_]);

    const positions = data?.positions ?? [];

    const filtered = positions
        .filter(p => filter === 'all' || p.direction === filter)
        .sort((a, b) => {
            if (sort === 'score') return (b.qualityScore ?? -1) - (a.qualityScore ?? -1);
            return b.weight - a.weight;
        });

    return (
        <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-slate-900/80 to-slate-950/90 backdrop-blur-xl shadow-2xl shadow-black/40 overflow-hidden">

            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.06] bg-white/[0.02]">
                <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500/20 to-orange-500/20 border border-white/10">
                        <Brain className="h-4 w-4 text-amber-400" />
                    </div>
                    <div>
                        <h3 className="text-[15px] font-semibold text-white tracking-tight">Business Quality · Munger Lens</h3>
                        <p className="text-[11px] text-gray-500 mt-0.5">ROIC · Pricing power · Owner earnings · Fortress balance sheet · Inversion</p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    {data && (
                        <span className="text-[9px] text-gray-600 bg-amber-500/10 border border-amber-500/15 px-2 py-0.5 rounded font-mono">
                            cached 1h
                        </span>
                    )}
                    <button
                        onClick={fetch_}
                        disabled={loading}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-600/15 hover:bg-amber-600/25 border border-amber-500/20 text-amber-300 text-[11px] font-semibold transition-all"
                    >
                        {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                        {loading ? 'Loading…' : 'Refresh'}
                    </button>
                </div>
            </div>

            {/* Loading state */}
            {loading && !data && (
                <div className="px-5 py-10 flex flex-col items-center gap-3">
                    <Loader2 className="h-8 w-8 animate-spin text-amber-400" />
                    <p className="text-sm text-gray-500 animate-pulse">
                        Fetching quality data for all positions… (may take ~20s)
                    </p>
                    <p className="text-[10px] text-gray-700">Results are cached for 1 hour after the first load.</p>
                </div>
            )}

            {/* Error state */}
            {error && !loading && (
                <div className="mx-5 my-4 flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3">
                    <AlertTriangle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" />
                    <p className="text-sm text-red-300">{error}</p>
                </div>
            )}

            {/* Data */}
            {data && !loading && (
                <div className="p-5 space-y-5">

                    {/* Summary cards */}
                    <QualitySummary positions={positions} />

                    {/* Concentration panel */}
                    <ConcentrationPanel positions={positions} />

                    {/* Filter + Sort bar */}
                    <div className="flex items-center justify-between">
                        <div className="flex gap-1 bg-white/[0.04] rounded-lg p-1 border border-white/[0.06]">
                            {(['all', 'Long', 'Short'] as const).map(f => (
                                <button
                                    key={f}
                                    onClick={() => setFilter(f)}
                                    className={cn(
                                        "px-3 py-1 text-[10px] font-semibold uppercase tracking-wider rounded-md transition-all",
                                        filter === f
                                            ? f === 'Long'  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                            : f === 'Short' ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                                            : "bg-amber-500/15 text-amber-300 border border-amber-500/20"
                                            : "text-gray-500 hover:text-gray-300"
                                    )}
                                >
                                    {f === 'all' ? 'All' : f}
                                </button>
                            ))}
                        </div>
                        <div className="flex gap-1 bg-white/[0.04] rounded-lg p-1 border border-white/[0.06]">
                            {(['score', 'weight'] as const).map(s => (
                                <button
                                    key={s}
                                    onClick={() => setSort(s)}
                                    className={cn(
                                        "px-3 py-1 text-[10px] font-semibold uppercase tracking-wider rounded-md transition-all",
                                        sort === s ? "bg-white/10 text-white" : "text-gray-500 hover:text-gray-300"
                                    )}
                                >
                                    {s === 'score' ? '↓ Quality Score' : '↓ Weight'}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Legend */}
                    <div className="flex flex-wrap items-center gap-4 text-[9px] text-gray-600">
                        <div className="flex items-center gap-1.5">
                            <span className="w-3 h-3 rounded-full bg-emerald-400" />
                            <span>Score ≥ 70 — Munger-grade compounder</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                            <span className="w-3 h-3 rounded-full bg-amber-400" />
                            <span>45–69 — Acceptable quality</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                            <span className="w-3 h-3 rounded-full bg-rose-400" />
                            <span>&lt; 45 — Low quality (fine as short)</span>
                        </div>
                        <span className="text-gray-700 ml-auto">ROIC = Return on Assets proxy · Click any row to expand</span>
                    </div>

                    {/* Position cards */}
                    <div className="space-y-2">
                        {filtered.map(pos => (
                            <PositionCard key={pos.ticker} pos={pos} />
                        ))}
                    </div>

                    {/* Munger quote footer */}
                    <div className="rounded-xl border border-amber-500/10 bg-amber-950/10 px-4 py-3">
                        <p className="text-[10px] text-amber-500/70 italic leading-relaxed">
                            "It's far better to buy a wonderful company at a fair price than a fair company at a wonderful price. Over the long term, the return on a business equals its return on invested capital."
                        </p>
                        <p className="text-[9px] text-gray-700 mt-1">— Charlie Munger</p>
                    </div>
                </div>
            )}
        </div>
    );
};
