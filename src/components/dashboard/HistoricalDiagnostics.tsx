import React from 'react';
import { Activity, BarChart3, ShieldAlert, Target } from 'lucide-react';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { cn } from '../../lib/utils';
import type { AnalyticsHistoryPoint } from '../../utils/finance';

type MetricKey = 'beta' | 'volatility' | 'drawdown' | 'battingAverage';

const formatPercent = (value: number | null | undefined, decimals = 1) =>
    typeof value === 'number' ? `${(value * 100).toFixed(decimals)}%` : '--';

const formatNumber = (value: number | null | undefined, decimals = 2) =>
    typeof value === 'number' ? value.toFixed(decimals) : '--';

const formatVariance = (value: number | null | undefined) =>
    typeof value === 'number' ? `${(value * 10000).toFixed(2)}` : '--';

const clean = (value: number | null | undefined) =>
    typeof value === 'number' && Number.isFinite(value) ? value : null;

const DiagnosticsTooltip = ({ active, payload, label, formatter }: {
    active?: boolean;
    payload?: Array<{ value?: number | null }>;
    label?: string;
    formatter: (value: number | null | undefined) => string;
}) => {
    if (!active || !payload?.length) return null;
    return (
        <div className="rounded-lg border border-white/10 bg-slate-950/95 px-3 py-2 shadow-xl">
            <div className="mb-1 font-mono text-[10px] text-gray-500">{label}</div>
            <div className="font-mono text-sm font-bold text-white">{formatter(payload[0]?.value ?? null)}</div>
        </div>
    );
};

const MetricPanel = ({
    title,
    subtitle,
    value,
    accent,
    dataKey,
    data,
    formatter,
    Icon,
}: {
    title: string;
    subtitle: string;
    value: string;
    accent: string;
    dataKey: MetricKey;
    data: AnalyticsHistoryPoint[];
    formatter: (value: number | null | undefined) => string;
    Icon: React.ComponentType<{ className?: string }>;
}) => (
    <div className="min-w-0 rounded-2xl border border-white/[0.07] bg-slate-950/70 p-4 shadow-lg shadow-black/20">
        <div className="mb-3 flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0">
                <div className="flex items-center gap-2">
                    <Icon className={cn('h-4 w-4 shrink-0', accent)} />
                    <h3 className="truncate text-[11px] font-bold uppercase tracking-[0.16em] text-gray-400">{title}</h3>
                </div>
                <p className="mt-1 truncate text-[10px] text-gray-600">{subtitle}</p>
            </div>
            <div className={cn('shrink-0 font-mono text-lg font-black tabular-nums', accent)}>{value}</div>
        </div>
        <div className="h-[92px] w-full">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: 4 }}>
                    <XAxis dataKey="date" hide />
                    <YAxis hide domain={['auto', 'auto']} />
                    <Tooltip content={<DiagnosticsTooltip formatter={formatter} />} />
                    <Line
                        type="monotone"
                        dataKey={dataKey}
                        stroke="currentColor"
                        strokeWidth={2}
                        dot={false}
                        connectNulls={false}
                        className={accent}
                        isAnimationActive={false}
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    </div>
);

export const HistoricalDiagnostics: React.FC<{ data: AnalyticsHistoryPoint[]; periodLabel?: string }> = React.memo(({ data, periodLabel = 'YTD' }) => {
    const points = data.map(point => ({
        ...point,
        beta: clean(point.beta),
        volatility: clean(point.volatility),
        drawdown: clean(point.drawdown),
        battingAverage: clean(point.battingAverage),
        variance: clean(point.variance),
    }));

    if (!points.length) return null;

    const latest = points[points.length - 1];
    const worstDrawdown = points.reduce((min, point) => {
        const value = clean(point.drawdown);
        return value === null ? min : Math.min(min, value);
    }, 0);

    return (
        <section className="rounded-2xl border border-white/[0.06] bg-gradient-to-b from-slate-900/55 to-slate-950/70 p-4 sm:p-5">
            <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <h2 className="text-sm font-black uppercase tracking-[0.18em] text-gray-300">Historical Diagnostics</h2>
                    <p className="text-xs text-gray-500">{periodLabel} risk, drawdown, and hit-rate path</p>
                </div>
                <div className="font-mono text-[11px] text-gray-500">
                    {points[0]?.date} to {latest?.date}
                </div>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricPanel
                    title="Beta"
                    subtitle="expanding sample"
                    value={formatNumber(latest.beta)}
                    accent="text-sky-300"
                    dataKey="beta"
                    data={points}
                    formatter={formatNumber}
                    Icon={Activity}
                />
                <MetricPanel
                    title="Variance"
                    subtitle={`daily var x10k: ${formatVariance(latest.variance)}`}
                    value={formatPercent(latest.volatility)}
                    accent="text-amber-300"
                    dataKey="volatility"
                    data={points}
                    formatter={formatPercent}
                    Icon={BarChart3}
                />
                <MetricPanel
                    title="Drawdown"
                    subtitle={`worst ${formatPercent(worstDrawdown)}`}
                    value={formatPercent(latest.drawdown)}
                    accent="text-rose-300"
                    dataKey="drawdown"
                    data={points}
                    formatter={formatPercent}
                    Icon={ShieldAlert}
                />
                <MetricPanel
                    title="Batting Avg"
                    subtitle={`${latest.winnersCount}W / ${latest.losersCount}L / ${latest.positionsCount} names`}
                    value={formatPercent(latest.battingAverage, 0)}
                    accent="text-emerald-300"
                    dataKey="battingAverage"
                    data={points}
                    formatter={(value) => formatPercent(value, 0)}
                    Icon={Target}
                />
            </div>
        </section>
    );
});
