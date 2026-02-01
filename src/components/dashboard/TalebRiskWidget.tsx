import React from 'react';
import type { TalebMetrics } from '../../utils/finance';
import { cn } from '../../lib/utils';
import { AlertTriangle, Activity, TrendingDown } from 'lucide-react';

interface TalebRiskWidgetProps {
    metrics?: TalebMetrics;
}

export const TalebRiskWidget: React.FC<TalebRiskWidgetProps> = ({ metrics }) => {
    if (!metrics) {
        return null;
    }

    const { Kurtosis, Skewness, Fat_Tail_Rating } = metrics;

    const getRatingColor = (rating: string) => {
        if (rating.includes('CRITICAL')) return 'text-rose-400 bg-rose-500/20 border-rose-500/30';
        if (rating === 'Moderate') return 'text-amber-400 bg-amber-500/20 border-amber-500/30';
        return 'text-emerald-400 bg-emerald-500/20 border-emerald-500/30';
    };

    const getRatingIcon = (rating: string) => {
        if (rating.includes('CRITICAL')) return <AlertTriangle className="h-5 w-5" />;
        if (rating === 'Moderate') return <Activity className="h-5 w-5" />;
        return <TrendingDown className="h-5 w-5" />;
    };

    return (
        <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-lg">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-amber-400" />
                Taleb "Turkey" Risk Scanner
            </h3>

            {/* Fat Tail Rating Badge */}
            <div className={cn(
                "rounded-lg border px-4 py-3 mb-4 flex items-center gap-3",
                getRatingColor(Fat_Tail_Rating)
            )}>
                {getRatingIcon(Fat_Tail_Rating)}
                <div>
                    <p className="text-xs uppercase tracking-wider opacity-70">Fat Tail Rating</p>
                    <p className="font-bold text-lg">{Fat_Tail_Rating}</p>
                </div>
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-2 gap-3">
                <div className="bg-white/5 rounded-lg p-3 border border-white/10">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Kurtosis (Excess)</p>
                    <p className="font-mono text-white text-lg">{Kurtosis?.toFixed(2) ?? 'N/A'}</p>
                    <p className="text-[10px] text-muted-foreground mt-1">
                        {Kurtosis > 3 ? '⚠️ Very fat tails' : Kurtosis > 1 ? '📊 Moderate tails' : '✅ Near-normal'}
                    </p>
                </div>
                <div className="bg-white/5 rounded-lg p-3 border border-white/10">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Skewness</p>
                    <p className="font-mono text-white text-lg">{Skewness?.toFixed(2) ?? 'N/A'}</p>
                    <p className="text-[10px] text-muted-foreground mt-1">
                        {Skewness < -1 ? '🚨 Heavy left tail' : Skewness < -0.5 ? '⚠️ Negative skew' : Skewness > 0.5 ? '📈 Positive skew' : '✅ Symmetric'}
                    </p>
                </div>
            </div>

            <p className="text-xs text-muted-foreground mt-4">
                <strong>Turkey Risk:</strong> Portfolios with high kurtosis & negative skew may appear stable but hide catastrophic tail events.
            </p>
        </div>
    );
};
