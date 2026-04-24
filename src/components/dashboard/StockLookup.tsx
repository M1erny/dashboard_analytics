import { useState, useRef, useEffect, useCallback } from 'react';
import { Search, TrendingUp, TrendingDown, Loader2, AlertCircle, X, DollarSign, BarChart2 } from 'lucide-react';
import { cn } from '../../lib/utils';

// ─── Types ────────────────────────────────────────────────────
interface Suggestion {
    symbol: string;
    name: string;
    exchange: string;
    type: string;
}

interface LookupResult {
    ticker: string;
    name: string;
    currency: string;
    currentPrice: number;
    r1d: number | null;
    r7d: number | null;
    r1m: number | null;
    rYtd: number | null;
    r1y: number | null;
    pe: number | null;
    fcfSbcYield: number | null;
    sbc_estimated: boolean;
    error?: string | null;
}

// ─── Helpers ──────────────────────────────────────────────────
const fmt = (v: number | null, decimals = 1): string => {
    if (v === null || v === undefined) return '—';
    const sign = v > 0 ? '+' : '';
    return `${sign}${(v * 100).toFixed(decimals)}%`;
};

const fmtVal = (v: number | null, decimals = 2): string => {
    if (v === null || v === undefined) return '—';
    const sign = v > 0 ? '+' : '';
    return `${sign}${(v * 100).toFixed(decimals)}%`;
};

const fmtPE = (v: number | null): string => {
    if (v === null || v === undefined) return '—';
    return `${v.toFixed(1)}×`;
};

const fmtPrice = (price: number, currency: string): string => {
    const symbols: Record<string, string> = {
        USD: '$', EUR: '€', GBP: '£', PLN: 'zł', JPY: '¥', KRW: '₩', DKK: 'kr',
    };
    const sym = symbols[currency] || currency + ' ';
    const decimals = price > 500 ? 0 : price > 10 ? 2 : 4;
    return `${sym}${price.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
};

const returnColor = (v: number | null): string => {
    if (v === null) return 'text-gray-500';
    if (v >= 0.10) return 'text-emerald-300 bg-emerald-900/40';
    if (v >= 0.02) return 'text-emerald-400 bg-emerald-900/25';
    if (v >= 0)    return 'text-emerald-500 bg-emerald-900/10';
    if (v >= -0.02) return 'text-red-400 bg-red-900/10';
    if (v >= -0.10) return 'text-red-400 bg-red-900/25';
    return 'text-red-300 bg-red-900/40';
};

const peColor = (v: number | null): string => {
    if (v === null) return 'text-gray-500';
    if (v < 0)  return 'text-red-400';
    if (v < 15) return 'text-emerald-400';
    if (v < 30) return 'text-yellow-400';
    return 'text-amber-400';
};

const yieldColor = (v: number | null): string => {
    if (v === null) return 'text-gray-500';
    if (v >= 0.07) return 'text-emerald-300';
    if (v >= 0.03) return 'text-emerald-400';
    if (v >= 0)    return 'text-yellow-400';
    return 'text-red-400';
};

// ─── Sub-components ───────────────────────────────────────────
const RetCell = ({ label, value }: { label: string; value: number | null }) => (
    <div className="flex flex-col items-center gap-1">
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold">{label}</span>
        <span className={cn('font-mono text-sm font-bold px-2 py-0.5 rounded-md', returnColor(value))}>
            {fmt(value)}
        </span>
    </div>
);

const ValTile = ({
    label, sublabel, value, color, estimated
}: {
    label: string; sublabel: string; value: string; color: string; estimated?: boolean;
}) => (
    <div className="flex flex-col gap-1.5 rounded-xl border border-white/[0.07] bg-white/[0.03] px-5 py-4 min-w-[160px]">
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold flex items-center gap-1">
            {label}
            {estimated && (
                <span title="SBC data unavailable — estimated as 0" className="text-amber-500/80 cursor-help">~</span>
            )}
        </span>
        <span className={cn('font-mono text-2xl font-black leading-none', color)}>{value}</span>
        <span className="text-[10px] text-gray-600 leading-snug">{sublabel}</span>
    </div>
);

// ─── Main Component ───────────────────────────────────────────
export const StockLookup = () => {
    const [query, setQuery]           = useState('');
    const [loading, setLoading]       = useState(false);
    const [result, setResult]         = useState<LookupResult | null>(null);
    const [errorMsg, setErrorMsg]     = useState<string | null>(null);
    const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
    const [sugLoading, setSugLoading] = useState(false);
    const [showDropdown, setShowDropdown] = useState(false);
    const [activeIdx, setActiveIdx]   = useState(-1);

    const inputRef    = useRef<HTMLInputElement>(null);
    const wrapperRef  = useRef<HTMLDivElement>(null);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const BASE_URL = import.meta.env.VITE_API_URL || '';

    // --- Autocomplete ---
    const fetchSuggestions = useCallback(async (q: string) => {
        if (q.trim().length < 1) { setSuggestions([]); return; }
        setSugLoading(true);
        try {
            const res = await fetch(`${BASE_URL}/api/lookup/suggest?query=${encodeURIComponent(q)}`);
            const data: Suggestion[] = await res.json();
            setSuggestions(data);
            setShowDropdown(data.length > 0);
        } catch {
            setSuggestions([]);
        } finally {
            setSugLoading(false);
        }
    }, [BASE_URL]);

    // Debounce typing → suggestions
    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        if (!query.trim()) { setSuggestions([]); setShowDropdown(false); return; }
        debounceRef.current = setTimeout(() => fetchSuggestions(query), 280);
        return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
    }, [query, fetchSuggestions]);

    // Close dropdown on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
                setShowDropdown(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    // --- Search ---
    const search = async (symbol: string) => {
        const trimmed = symbol.trim();
        if (!trimmed) return;
        setShowDropdown(false);
        setSuggestions([]);
        setLoading(true);
        setResult(null);
        setErrorMsg(null);
        try {
            const res  = await fetch(`${BASE_URL}/api/lookup?query=${encodeURIComponent(trimmed)}`);
            const data: LookupResult = await res.json();
            if (data.error) setErrorMsg(data.error);
            else setResult(data);
        } catch {
            setErrorMsg('Failed to connect to backend. Is the server running?');
        } finally {
            setLoading(false);
        }
    };

    const selectSuggestion = (s: Suggestion) => {
        setQuery(s.symbol);
        search(s.symbol);
    };

    const clear = () => {
        setQuery(''); setResult(null); setErrorMsg(null);
        setSuggestions([]); setShowDropdown(false); setActiveIdx(-1);
        inputRef.current?.focus();
    };

    // Keyboard navigation in dropdown
    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (!showDropdown || suggestions.length === 0) {
            if (e.key === 'Enter') search(query);
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActiveIdx(i => Math.min(i + 1, suggestions.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActiveIdx(i => Math.max(i - 1, -1));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (activeIdx >= 0) selectSuggestion(suggestions[activeIdx]);
            else search(query);
        } else if (e.key === 'Escape') {
            setShowDropdown(false);
            setActiveIdx(-1);
        }
    };

    return (
        <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-slate-900/80 to-slate-950/90 backdrop-blur-xl shadow-2xl shadow-black/40 overflow-hidden">

            {/* Header */}
            <div className="flex items-center gap-3 px-5 py-3.5 border-b border-white/[0.06] bg-white/[0.02]">
                <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500/20 to-indigo-500/20 border border-white/10">
                    <Search className="h-4 w-4 text-violet-400" />
                </div>
                <div>
                    <h3 className="text-[15px] font-semibold text-white tracking-tight">Stock Lookup</h3>
                    <p className="text-[11px] text-gray-500 mt-0.5">Search any global ticker for returns & valuation</p>
                </div>
            </div>

            {/* Search Bar */}
            <div className="px-5 py-4 border-b border-white/[0.04]">
                <div className="flex gap-3">
                    <div ref={wrapperRef} className="relative flex-1">
                        <Search className="absolute left-3 top-[13px] h-4 w-4 text-gray-500 pointer-events-none z-10" />
                        <input
                            ref={inputRef}
                            id="stock-lookup-input"
                            type="text"
                            value={query}
                            onChange={e => { setQuery(e.target.value); setActiveIdx(-1); }}
                            onKeyDown={handleKeyDown}
                            onFocus={() => suggestions.length > 0 && setShowDropdown(true)}
                            placeholder="e.g. Apple, AMZN, CDR.WA, BRK-B…"
                            autoComplete="off"
                            className={cn(
                                "w-full pl-10 pr-10 py-2.5 rounded-xl text-sm",
                                "bg-white/[0.06] border border-white/[0.10] text-white placeholder-gray-600",
                                "focus:outline-none focus:ring-1 focus:ring-violet-500/50 focus:border-violet-500/40",
                                "transition-all duration-200"
                            )}
                        />
                        {/* Clear / spinner inline */}
                        <div className="absolute right-3 top-[13px]">
                            {sugLoading
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-500" />
                                : query
                                    ? <button onClick={clear}><X className="h-3.5 w-3.5 text-gray-500 hover:text-gray-300 transition-colors" /></button>
                                    : null
                            }
                        </div>

                        {/* Dropdown */}
                        {showDropdown && suggestions.length > 0 && (
                            <div className="absolute top-full mt-1.5 left-0 right-0 z-50 rounded-xl border border-white/[0.10] bg-slate-900/98 backdrop-blur-xl shadow-2xl shadow-black/60 overflow-hidden">
                                {suggestions.map((s, i) => (
                                    <button
                                        key={s.symbol}
                                        onMouseDown={() => selectSuggestion(s)}
                                        className={cn(
                                            "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors",
                                            i === activeIdx
                                                ? "bg-violet-600/20 text-white"
                                                : "hover:bg-white/[0.05] text-gray-200",
                                            i < suggestions.length - 1 && "border-b border-white/[0.04]"
                                        )}
                                    >
                                        <div className="flex flex-col flex-1 min-w-0">
                                            <span className="font-mono text-sm font-bold text-white leading-none">{s.symbol}</span>
                                            <span className="text-[11px] text-gray-500 truncate mt-0.5">{s.name}</span>
                                        </div>
                                        <span className="text-[10px] text-gray-600 font-mono shrink-0">{s.exchange}</span>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    <button
                        id="stock-lookup-search-btn"
                        onClick={() => search(query)}
                        disabled={loading || !query.trim()}
                        className={cn(
                            "flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold shrink-0",
                            "bg-violet-600/80 hover:bg-violet-600 border border-violet-500/40",
                            "text-white transition-all duration-200",
                            "disabled:opacity-40 disabled:cursor-not-allowed"
                        )}
                    >
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                        {loading ? 'Fetching…' : 'Search'}
                    </button>
                </div>
            </div>

            {/* Loading */}
            {loading && (
                <div className="px-5 py-8 flex flex-col items-center gap-3">
                    <Loader2 className="h-8 w-8 animate-spin text-violet-400" />
                    <p className="text-sm text-gray-500 animate-pulse">Fetching data from Yahoo Finance…</p>
                </div>
            )}

            {/* Error */}
            {errorMsg && !loading && (
                <div className="mx-5 my-4 flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3">
                    <AlertCircle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" />
                    <p className="text-sm text-red-300">{errorMsg}</p>
                </div>
            )}

            {/* Result Card */}
            {result && !loading && (
                <div className="px-5 py-5 space-y-4">

                    {/* Name + Price */}
                    <div className="flex flex-col sm:flex-row sm:items-end gap-2 sm:gap-4">
                        <div>
                            <p className="text-[11px] text-gray-500 uppercase tracking-widest font-semibold">{result.ticker}</p>
                            <h4 className="text-xl font-black text-white leading-tight">{result.name}</h4>
                        </div>
                        <div className="sm:ml-auto flex items-end gap-2">
                            <span className="font-mono text-3xl font-black text-white leading-none">
                                {fmtPrice(result.currentPrice, result.currency)}
                            </span>
                            <span className={cn('font-mono text-sm font-semibold mb-0.5 px-2 py-0.5 rounded-md flex items-center gap-1', returnColor(result.r1d))}>
                                {result.r1d !== null && (result.r1d >= 0
                                    ? <TrendingUp className="h-3 w-3" />
                                    : <TrendingDown className="h-3 w-3" />)}
                                {fmt(result.r1d)} today
                            </span>
                        </div>
                    </div>

                    {/* Returns */}
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                        <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-3 flex items-center gap-1.5">
                            <BarChart2 className="h-3 w-3" /> Price Returns
                        </p>
                        <div className="flex flex-wrap gap-4 justify-around">
                            <RetCell label="1D"  value={result.r1d} />
                            <RetCell label="7D"  value={result.r7d} />
                            <RetCell label="1M"  value={result.r1m} />
                            <RetCell label="YTD" value={result.rYtd} />
                            <RetCell label="1Y"  value={result.r1y} />
                        </div>
                    </div>

                    {/* Valuation */}
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
                        <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-3 flex items-center gap-1.5">
                            <DollarSign className="h-3 w-3" /> Valuation
                        </p>
                        <div className="flex flex-wrap gap-3">
                            <ValTile
                                label="TTM P/E"
                                sublabel="Trailing 12-month Price / Earnings"
                                value={fmtPE(result.pe)}
                                color={peColor(result.pe)}
                            />
                            <ValTile
                                label="(FCF − SBC) / EV"
                                sublabel={`Owner earnings yield${result.sbc_estimated ? ' — SBC est. as 0' : ''}`}
                                value={fmtVal(result.fcfSbcYield)}
                                color={yieldColor(result.fcfSbcYield)}
                                estimated={result.sbc_estimated}
                            />
                        </div>
                    </div>
                </div>
            )}

            {/* Empty state */}
            {!result && !loading && !errorMsg && (
                <div className="px-5 py-8 flex flex-col items-center gap-4 text-center">
                    <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-violet-500/10 border border-violet-500/20">
                        <Search className="h-5 w-5 text-violet-400/60" />
                    </div>
                    <div>
                        <p className="text-sm text-gray-400 font-medium">Search any global stock</p>
                        <p className="text-[11px] text-gray-600 mt-1">US, European, and Asian exchanges supported.</p>
                    </div>
                    <div className="flex flex-wrap justify-center gap-2 mt-1">
                        {['AAPL', 'MSFT', 'NVDA', 'BRK-B', 'CDR.WA', 'NOVO-B.CO'].map(ticker => (
                            <button
                                key={ticker}
                                onClick={() => { setQuery(ticker); search(ticker); }}
                                className="px-3 py-1.5 rounded-lg text-[11px] font-mono font-semibold bg-white/[0.04] border border-white/[0.08] text-gray-400 hover:bg-violet-500/15 hover:border-violet-500/30 hover:text-violet-300 transition-all duration-200"
                            >
                                {ticker}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};
