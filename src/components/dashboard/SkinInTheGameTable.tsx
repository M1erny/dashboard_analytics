import React from 'react';
import type { InsiderInfo, PeriodicReturn } from '../../utils/finance';
import { cn } from '../../lib/utils';
import { Users, TrendingUp, TrendingDown, MinusCircle, AlertCircle } from 'lucide-react';

interface SkinInTheGameTableProps {
    insiderData?: Record<string, InsiderInfo>;
    periodicReturns?: PeriodicReturn[];
}

export const SkinInTheGameTable: React.FC<SkinInTheGameTableProps> = ({ insiderData, periodicReturns }) => {
    if (!insiderData || Object.keys(insiderData).length === 0) {
        return null;
    }

    // Merge with periodic returns for weight/direction context
    const holdings = Object.entries(insiderData).map(([ticker, info]) => {
        const returnInfo = periodicReturns?.find(p => p.ticker === ticker);
        return {
            ticker,
            ...info,
            weight: returnInfo?.weight,
            direction: returnInfo?.direction
        };
    });

    // Sort by signal importance: Selling first, then Buying, then Neutral
    const signalOrder: Record<string, number> = { 'Selling': 0, 'High Buying': 1, 'Neutral': 2, 'Error': 3 };
    holdings.sort((a, b) => (signalOrder[a.Signal] ?? 99) - (signalOrder[b.Signal] ?? 99));

    const getSignalStyle = (signal: string) => {
        if (signal === 'High Buying') return { color: 'text-emerald-400', bg: 'bg-emerald-500/20', icon: <TrendingUp className="h-4 w-4" /> };
        if (signal === 'Selling') return { color: 'text-rose-400', bg: 'bg-rose-500/20', icon: <TrendingDown className="h-4 w-4" /> };
        if (signal === 'Error') return { color: 'text-gray-500', bg: 'bg-gray-500/20', icon: <AlertCircle className="h-4 w-4" /> };
        return { color: 'text-gray-400', bg: 'bg-gray-500/10', icon: <MinusCircle className="h-4 w-4" /> };
    };

    return (
        <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-lg">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <Users className="h-5 w-5 text-violet-400" />
                Skin in the Game (Insider Alignment)
            </h3>

            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="text-left text-muted-foreground text-xs uppercase tracking-wider border-b border-white/10">
                            <th className="pb-2 pr-4">Ticker</th>
                            <th className="pb-2 pr-4">Position</th>
                            <th className="pb-2 pr-4">Insider Signal</th>
                            <th className="pb-2 pr-4">Details</th>
                            <th className="pb-2">Held by Insiders</th>
                        </tr>
                    </thead>
                    <tbody>
                        {holdings.map((h) => {
                            const style = getSignalStyle(h.Signal);
                            return (
                                <tr key={h.ticker} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                                    <td className="py-2 pr-4 font-mono text-white">{h.ticker}</td>
                                    <td className="py-2 pr-4">
                                        {h.direction && h.weight != null ? (
                                            <span className={cn(
                                                "text-xs px-2 py-0.5 rounded",
                                                h.direction === 'Long' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                                            )}>
                                                {h.direction} {(h.weight * 100).toFixed(0)}%
                                            </span>
                                        ) : (
                                            <span className="text-gray-500">—</span>
                                        )}
                                    </td>
                                    <td className="py-2 pr-4">
                                        <span className={cn("flex items-center gap-1.5 text-xs px-2 py-1 rounded w-fit", style.bg, style.color)}>
                                            {style.icon}
                                            {h.Signal}
                                        </span>
                                    </td>
                                    <td className="py-2 pr-4 text-muted-foreground text-xs">{h.Details}</td>
                                    <td className="py-2 font-mono text-white">{h.Held_Pct}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            <p className="text-xs text-muted-foreground mt-4">
                <strong>Taleb Principle:</strong> Prefer companies where insiders have "Skin in the Game" — they share downside risk with shareholders.
            </p>
        </div>
    );
};
