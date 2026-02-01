import React, { useEffect, useState } from 'react';
import { fetchDashboardData } from '../utils/finance';
import type { FullRiskReport } from '../utils/finance';
import { ExecutiveSummary } from './dashboard/ExecutiveSummary';
import { ReturnsHeatmap } from './dashboard/ReturnsHeatmap';
import { CorrelationMatrixTable } from './dashboard/CorrelationMatrixTable';
import { FxExposureWidget } from './dashboard/FxExposureWidget';
import { LayoutDashboard, ShieldCheck, RefreshCw } from 'lucide-react';
import { cn } from '../lib/utils';
import {
    ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip,
    CartesianGrid, Legend
} from 'recharts';

export const Dashboard: React.FC = () => {
    const [data, setData] = useState<FullRiskReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        fetchDashboardData().then(res => {
            if (res) {
                if (res.error) {
                    setError(res.error);
                } else {
                    setData(res);
                }
            } else {
                setError("Failed to connect to backend API. Please check if the server is running.");
            }
        }).catch(err => {
            setError(err instanceof Error ? err.message : String(err));
        }).finally(() => {
            setLoading(false);
        });
    }, []);

    const formatPercent = (val: number | undefined) => typeof val === 'number' ? `${(val * 100).toFixed(2)}%` : 'N/A';

    if (loading) {
        return (
            <div className="min-h-screen bg-background text-foreground flex items-center justify-center">
                <div className="flex flex-col items-center gap-4">
                    <div className="h-12 w-12 animate-spin rounded-full border-4 border-primary border-t-transparent" />
                    <p className="text-muted-foreground animate-pulse">Running Risk Engine...</p>
                </div>
            </div>
        )
    }

    if (error || !data) {
        return (
            <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-4">
                <div className="max-w-md w-full bg-rose-500/10 border border-rose-500/20 rounded-xl p-6 text-center">
                    <ShieldCheck className="h-12 w-12 text-rose-500 mx-auto mb-4" />
                    <h2 className="text-xl font-bold text-white mb-2">Dashboard Error</h2>
                    <p className="text-gray-300 mb-4">{error || "No data received from backend."}</p>
                    <button
                        onClick={() => window.location.reload()}
                        className="bg-rose-500 hover:bg-rose-600 text-white px-4 py-2 rounded-lg transition-colors"
                    >
                        Retry Connection
                    </button>
                    <div className="mt-4 text-xs text-gray-500 text-left bg-black/20 p-2 rounded overflow-auto max-h-32">
                        <p>Troubleshooting:</p>
                        <ul className="list-disc list-inside mt-1">
                            <li>Ensure the backend window is open</li>
                            <li>Check for errors in the backend console</li>
                            <li>Verify http://127.0.0.1:8000/api/metrics works in browser</li>
                        </ul>
                    </div>
                </div>
            </div>
        )
    }

    const { vitals, leverage, history, periodicReturns, volumeWeightedCorrelation } = data;

    return (
        <div className="min-h-screen bg-background text-foreground p-4 md:p-8">
            <div className="mx-auto max-w-[1600px] space-y-6 md:space-y-8">

                {/* Responsive Header */}
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div>
                        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white flex items-center gap-2">
                            <LayoutDashboard className="h-6 w-6 md:h-8 md:w-8 text-primary" />
                            Institutional Risk Dashboard
                        </h1>
                        <p className="text-muted-foreground mt-1 text-sm md:text-base">
                            Live quantitative analysis • {history[history.length - 1]?.date}
                        </p>
                    </div>

                    {/* Header Widgets: Exposures & FX */}
                    <div className="flex flex-wrap md:flex-nowrap gap-3 text-sm w-full md:w-auto">
                        <FxExposureWidget vitals={vitals} />

                        <div className="flex-1 md:flex-none bg-white/5 px-4 py-2 rounded-lg border border-white/10 flex flex-col justify-center min-w-[120px]">
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Long Exposure</p>
                            <p className="font-mono text-emerald-400 font-bold text-base">{formatPercent(leverage.Long_Exp)}</p>
                        </div>
                        <div className="flex-1 md:flex-none bg-white/5 px-4 py-2 rounded-lg border border-white/10 flex flex-col justify-center min-w-[120px]">
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Short Exposure</p>
                            <p className="font-mono text-rose-400 font-bold text-base">{formatPercent(leverage.Short_Exp)}</p>
                        </div>

                        {/* Refresh Button - Fixed Alignment */}
                        <button
                            onClick={() => {
                                setLoading(true);
                                fetchDashboardData(5, 1000, true).then(res => { // force=true
                                    if (res) setData(res);
                                }).finally(() => setLoading(false));
                            }}
                            className="bg-white/5 hover:bg-white/10 px-4 rounded-lg border border-white/10 transition-colors flex items-center justify-center"
                            title="Force Refresh Data"
                        >
                            <RefreshCw className={cn("h-5 w-5 text-emerald-400", loading ? "animate-spin" : "")} />
                        </button>
                    </div>
                </div>

                {/* NEW: Executive Summary (YTD Returns, Alpha, Benchmarks) */}
                <ExecutiveSummary vitals={vitals} />

                {/* ROW 2: Returns Heatmap & Portfolio Contribution */}
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                    <ReturnsHeatmap periodicReturns={periodicReturns} />
                    <CorrelationMatrixTable data={volumeWeightedCorrelation} />
                </div>

                {/* ROW 3: Performance Chart (Full Width) */}
                <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-lg h-[400px]">
                    <h3 className="text-lg font-semibold text-white mb-4">Cumulative Performance vs Benchmark</h3>
                    <div className="h-[calc(100%-2rem)]">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={history}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                                <XAxis dataKey="date" hide />
                                <YAxis domain={['auto', 'auto']} tickFormatter={(v) => `$${v}`} stroke="#666" fontSize={11} tickLine={false} axisLine={false} />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155' }}
                                    formatter={(val) => val !== undefined ? [`$${Number(val).toFixed(0)}`, ''] : ['', '']}
                                    labelStyle={{ color: '#94a3b8' }}
                                />
                                <Legend />
                                <Line type="monotone" dataKey="portfolio" name="Portfolio" stroke="#8b5cf6" strokeWidth={2} dot={false} />
                                <Line type="monotone" dataKey="benchmark" name="Market (SPY)" stroke="#64748b" strokeWidth={2} strokeDasharray="4 4" dot={false} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>

            </div>
        </div>
    );
};
