import React, { useState, useRef, useEffect } from 'react';
import { Banknote, ChevronDown } from 'lucide-react';
import type { Vitals } from '../../utils/finance';
import { cn } from '../../lib/utils';

interface FxExposureWidgetProps {
    vitals: Vitals;
}

export const FxExposureWidget: React.FC<FxExposureWidgetProps> = ({ vitals }) => {
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

    // Check if we have exposure data
    const exposure = vitals.currencyExposure || {};
    const entries = Object.entries(exposure).sort(([, a], [, b]) => b - a);

    // Close on click outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    if (entries.length === 0) return null;

    return (
        <div className="relative" ref={containerRef}>
            <button
                onClick={() => setIsOpen(!isOpen)}
                className={cn(
                    "flex flex-col items-start justify-center px-4 py-2 rounded-lg border transition-all duration-200 w-full md:w-auto",
                    isOpen
                        ? "bg-emerald-500/20 border-emerald-500/50"
                        : "bg-white/5 border-white/10 hover:bg-white/10"
                )}
            >
                <div className="flex items-center gap-2 text-muted-foreground text-xs uppercase tracking-wide font-medium">
                    <Banknote className="h-3 w-3" />
                    <span>FX Exposure</span>
                    <ChevronDown className={cn("h-3 w-3 transition-transform", isOpen && "rotate-180")} />
                </div>
                <div className="font-mono text-emerald-400 text-sm font-bold flex gap-2 mt-0.5">
                    {/* Show top 2 currencies as preview */}
                    {entries.slice(0, 2).map(([curr, share]) => (
                        <span key={curr}>
                            {curr} <span className="opacity-80">{(share * 100).toFixed(0)}%</span>
                        </span>
                    ))}
                    {entries.length > 2 && <span className="text-muted-foreground text-xs self-center">+{entries.length - 2}</span>}
                </div>
            </button>

            {/* Dropdown / Popover */}
            {isOpen && (
                <div className="absolute right-0 top-full mt-2 w-full md:w-72 bg-[#0f172a] border border-white/10 rounded-xl shadow-2xl p-4 z-50 backdrop-blur-xl animate-in fade-in zoom-in-95 origin-top-right">

                    {/* Portfolio Currency Exposure */}
                    <h4 className="text-white font-medium mb-3 text-xs uppercase tracking-wider border-b border-white/5 pb-2">Portfolio Exposure</h4>
                    <div className="space-y-2 mb-6">
                        {entries.map(([curr, share]) => (
                            <div key={curr} className="flex justify-between items-center group">
                                <div className="flex items-center gap-2">
                                    <div className="w-1 h-6 rounded bg-white/10 relative overflow-hidden">
                                        <div
                                            className="absolute bottom-0 left-0 w-full bg-emerald-500 rounded transition-all duration-500"
                                            style={{ height: `${Math.min(share * 100, 100)}%` }}
                                        />
                                    </div>
                                    <span className="text-gray-300 font-bold text-sm">{curr}</span>
                                </div>
                                <span className="font-mono text-white text-sm">{(share * 100).toFixed(1)}%</span>
                            </div>
                        ))}
                    </div>

                    {/* NEW: FX Market Matrix */}
                    <h4 className="text-white font-medium mb-3 text-xs uppercase tracking-wider border-b border-white/5 pb-2">FX Market (YTD)</h4>
                    <div className="grid grid-cols-2 gap-2">
                        {vitals.fxWatchlist && Object.entries(vitals.fxWatchlist).map(([pair, ytd]) => (
                            <div key={pair} className="bg-white/5 rounded p-2 flex flex-col items-center justify-center">
                                <span className="text-[10px] text-gray-400 font-semibold mb-0.5">{pair.replace('=X', '')}</span>
                                <span className={cn("font-mono font-bold text-sm", ytd >= 0 ? "text-emerald-400" : "text-rose-400")}>
                                    {ytd > 0 ? '+' : ''}{(ytd * 100).toFixed(2)}%
                                </span>
                            </div>
                        ))}
                        {(!vitals.fxWatchlist || Object.keys(vitals.fxWatchlist).length === 0) && (
                            <span className="text-xs text-gray-500 col-span-2 text-center py-2">No FX data available</span>
                        )}
                    </div>

                </div>
            )}
        </div>
    );
};
