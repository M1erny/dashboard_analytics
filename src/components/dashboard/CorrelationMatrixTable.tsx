import React from 'react';
import type { CorrelationMatrix } from '../../utils/finance';

interface Props {
    data?: CorrelationMatrix;
}

export const CorrelationMatrixTable: React.FC<Props> = ({ data }) => {
    if (!data || !data.matrix || data.matrix.length === 0) {
        return null;
    }

    const { tickers, matrix } = data;

    // Helper for color scale
    const getColor = (val: number | null) => {
        if (val === null) return 'bg-gray-800 text-gray-500';

        // Scale: -1 (Red) to 0 (Gray) to 1 (Green)
        // Tailwind classes are static, so we use inline styles for dynamic opacity or specific classes
        // Let's use simplified buckets for efficiency and tailored look

        if (val === 1) return 'bg-emerald-500/20 text-emerald-400 font-bold'; // Self correlation

        if (val > 0.8) return 'bg-emerald-500/30 text-emerald-300';
        if (val > 0.5) return 'bg-emerald-500/20 text-emerald-400';
        if (val > 0.2) return 'bg-emerald-500/10 text-emerald-500';

        if (val < -0.8) return 'bg-rose-500/30 text-rose-300';
        if (val < -0.5) return 'bg-rose-500/20 text-rose-400';
        if (val < -0.2) return 'bg-rose-500/10 text-rose-500';

        return 'text-gray-400'; // Near zero
    };

    return (
        <div className="rounded-xl border border-white/10 bg-white/5 p-6 backdrop-blur-lg overflow-hidden">
            <h3 className="text-lg font-semibold text-white mb-4">Volume Weighted Correlation Matrix (1Y)</h3>

            <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">
                    <thead>
                        <tr>
                            <th className="p-2 text-left min-w-[80px]"></th>
                            {tickers.map(t => (
                                <th key={t} className="p-2 text-center text-muted-foreground font-medium min-w-[60px]">
                                    {t}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {tickers.map((rowTicker, i) => (
                            <tr key={rowTicker} className="border-t border-white/5 hover:bg-white/5 transition-colors">
                                {/* Row Header */}
                                <td className="p-2 font-medium text-gray-300 sticky left-0 bg-[#0c0a09] border-r border-white/10">
                                    {rowTicker}
                                </td>

                                {/* Cells */}
                                {matrix[i].map((val, j) => (
                                    <td key={`${rowTicker}-${tickers[j]}`} className="p-1">
                                        <div
                                            className={`
                                                w-full h-8 flex items-center justify-center rounded 
                                                ${getColor(val)}
                                                ${i === j ? 'border border-white/10' : ''}
                                            `}
                                            title={`${rowTicker} vs ${tickers[j]}: ${val?.toFixed(4) ?? 'N/A'}`}
                                        >
                                            {val !== null ? val.toFixed(2) : '-'}
                                        </div>
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
