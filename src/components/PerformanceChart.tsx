import React from 'react';
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    Legend
} from 'recharts';
import type { HistoryPoint } from '../utils/finance';
import { cn } from '../lib/utils';

interface PerformanceChartProps {
    data: HistoryPoint[];
    className?: string;
}

export const PerformanceChart: React.FC<PerformanceChartProps> = ({ data, className }) => {
    return (
        <div className={cn("h-[400px] w-full rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-lg", className)}>
            <div className="mb-4">
                <h3 className="text-lg font-semibold text-white">Performance History (2026)</h3>
                <p className="text-sm text-muted-foreground">Cumulative return comparison</p>
            </div>

            <ResponsiveContainer width="100%" height="90%">
                <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" vertical={false} />
                    <XAxis
                        dataKey="date"
                        stroke="#888888"
                        tickFormatter={(value: string) => new Date(value).toLocaleDateString('en-US', { month: 'short' })}
                        minTickGap={30}
                        tick={{ fontSize: 12 }}
                        tickLine={false}
                        axisLine={false}
                    />
                    <YAxis
                        stroke="#888888"
                        tickFormatter={(value: number) => `$${value}`}
                        domain={['auto', 'auto']}
                        tick={{ fontSize: 12 }}
                        tickLine={false}
                        axisLine={false}
                    />
                    <Tooltip
                        contentStyle={{ backgroundColor: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px' }}
                        itemStyle={{ fontSize: '12px' }}
                        formatter={(value: number | undefined) => [value !== undefined ? `$${value.toFixed(2)}` : 'N/A', '']}
                        labelFormatter={(label) => new Date(label).toLocaleDateString('en-US', { dateStyle: 'medium' })}
                    />
                    <Legend wrapperStyle={{ paddingTop: '20px' }} />
                    <Line
                        type="monotone"
                        dataKey="portfolioPrice"
                        name="Portfolio"
                        stroke="#8b5cf6"
                        strokeWidth={3}
                        dot={false}
                        activeDot={{ r: 6, strokeWidth: 0 }}
                    />
                    <Line
                        type="monotone"
                        dataKey="benchmarkPrice"
                        name="Benchmark"
                        stroke="#64748b"
                        strokeWidth={2}
                        strokeDasharray="5 5" // Dashed line for benchmark
                        dot={false}
                        activeDot={{ r: 6, strokeWidth: 0 }}
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
};
