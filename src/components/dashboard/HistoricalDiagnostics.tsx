import React from 'react';
import { Activity, BarChart3, ChartNoAxesCombined, ShieldAlert } from 'lucide-react';
import {
    CartesianGrid,
    Line,
    LineChart,
    ReferenceLine,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts';
import { cn } from '../../lib/utils';
import type { AnalyticsHistoryPoint, HistoryPoint } from '../../utils/finance';

type MetricKey = 'beta' | 'volatility' | 'drawdown';

interface GrossPerformancePoint {
    date: string;
    portfolioGross: number;
    benchmark: number;
    spread: number;
}

const formatPercent = (value: number | null | undefined, decimals = 1) =>
    typeof value === 'number' ? `${(value * 100).toFixed(decimals)}%` : '--';

const formatSignedPercent = (value: number | null | undefined, decimals = 1) =>
    typeof value === 'number'
        ? `${value >= 0 ? '+' : ''}${(value * 100).toFixed(decimals)}%`
        : '--';

const formatSpread = (value: number | null | undefined, decimals = 1) =>
    typeof value === 'number'
        ? `${value >= 0 ? '+' : ''}${(value * 100).toFixed(decimals)} pp`
        : '--';

const formatNumber = (value: number | null | undefined, decimals = 2) =>
    typeof value === 'number' ? value.toFixed(decimals) : '--';

const formatVariance = (value: number | null | undefined) =>
    typeof value === 'number' ? `${(value * 10000).toFixed(2)}` : '--';

const clean = (value: number | null | undefined) =>
    typeof value === 'number' && Number.isFinite(value) ? value : null;

const formatDate = (value: string, includeYear = true) => {
    const [year, month, day] = value.split('-').map(Number);
    if (!year || !month || !day) return value;
    return new Intl.DateTimeFormat('en-GB', {
        day: '2-digit',
        month: 'short',
        ...(includeYear ? { year: 'numeric' } : {}),
        timeZone: 'UTC',
    }).format(new Date(Date.UTC(year, month - 1, day)));
};

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

const GrossPerformanceTooltip = ({ active, payload, label }: {
    active?: boolean;
    payload?: Array<{ payload?: GrossPerformancePoint }>;
    label?: string;
}) => {
    const point = payload?.[0]?.payload;
    if (!active || !point) return null;

    return (
        <div className="min-w-[210px] rounded-lg border border-white/10 bg-slate-950/95 p-3 shadow-2xl">
            <div className="mb-3 font-mono text-[11px] font-semibold text-gray-400">
                {formatDate(label ?? point.date)}
            </div>
            <div className="space-y-2 font-mono text-xs tabular-nums">
                <div className="flex items-center justify-between gap-5">
                    <span className="flex items-center gap-2 text-gray-400">
                        <span className="h-2 w-2 rounded-full bg-emerald-400" /> Portfolio gross
                    </span>
                    <span className="font-bold text-emerald-300">{formatSignedPercent(point.portfolioGross, 2)}</span>
                </div>
                <div className="flex items-center justify-between gap-5">
                    <span className="flex items-center gap-2 text-gray-400">
                        <span className="h-0 w-3 border-t-2 border-dashed border-emerald-700" /> S&amp;P 500
                    </span>
                    <span className="font-bold text-emerald-600">{formatSignedPercent(point.benchmark, 2)}</span>
                </div>
                <div className="flex items-center justify-between gap-5 border-t border-white/[0.08] pt-2">
                    <span className="flex items-center gap-2 text-gray-400">
                        <span className="h-0 w-3 border-t-2 border-dashed border-amber-300" /> Spread
                    </span>
                    <span className="font-bold text-amber-300">{formatSpread(point.spread, 2)}</span>
                </div>
            </div>
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
    <div className="min-w-0 rounded-lg border border-white/[0.07] bg-slate-950/70 p-4 shadow-lg shadow-black/20">
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
                        type="linear"
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

const GrossPerformanceChart = ({ data, periodLabel }: { data: GrossPerformancePoint[]; periodLabel: string }) => {
    if (!data.length) {
        return (
            <div className="rounded-lg border border-white/[0.07] bg-slate-950/70 p-5 text-sm text-gray-500">
                Gross performance history will appear after the backend data refreshes.
            </div>
        );
    }

    const latest = data[data.length - 1];

    return (
        <div className="rounded-lg border border-white/[0.07] bg-slate-950/70 p-4 shadow-lg shadow-black/20 sm:p-5">
            <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                    <div className="flex items-center gap-2">
                        <ChartNoAxesCombined className="h-4 w-4 shrink-0 text-emerald-300" />
                        <h3 className="text-[11px] font-bold uppercase tracking-[0.16em] text-gray-300">
                            Gross Performance vs S&amp;P 500
                        </h3>
                    </div>
                    <p className="mt-1 text-[11px] text-gray-500">
                        Daily cumulative return before financing costs; spread is portfolio minus benchmark.
                    </p>
                </div>
                <div className="grid grid-cols-3 gap-x-5 gap-y-2 font-mono text-[11px] tabular-nums sm:flex sm:flex-wrap sm:justify-end">
                    <div>
                        <div className="mb-1 flex items-center gap-1.5 text-[9px] uppercase tracking-[0.12em] text-gray-500">
                            <span className="h-2 w-2 rounded-full bg-emerald-400" /> Portfolio
                        </div>
                        <div className="font-bold text-emerald-300">{formatSignedPercent(latest.portfolioGross)}</div>
                    </div>
                    <div>
                        <div className="mb-1 flex items-center gap-1.5 text-[9px] uppercase tracking-[0.12em] text-gray-500">
                            <span className="h-0 w-3 border-t-2 border-dashed border-emerald-700" /> S&amp;P 500
                        </div>
                        <div className="font-bold text-emerald-600">{formatSignedPercent(latest.benchmark)}</div>
                    </div>
                    <div>
                        <div className="mb-1 flex items-center gap-1.5 text-[9px] uppercase tracking-[0.12em] text-gray-500">
                            <span className="h-0 w-3 border-t-2 border-dashed border-amber-300" /> Spread
                        </div>
                        <div className="font-bold text-amber-300">{formatSpread(latest.spread)}</div>
                    </div>
                </div>
            </div>

            <div className="h-[270px] w-full sm:h-[320px]">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                        <CartesianGrid vertical={false} stroke="rgba(90, 150, 90, 0.10)" />
                        <XAxis
                            dataKey="date"
                            axisLine={false}
                            tickLine={false}
                            minTickGap={42}
                            tick={{ fill: '#517051', fontSize: 10, fontFamily: 'monospace' }}
                            tickFormatter={(value: string) => formatDate(value, false)}
                        />
                        <YAxis
                            axisLine={false}
                            tickLine={false}
                            width={48}
                            tick={{ fill: '#517051', fontSize: 10, fontFamily: 'monospace' }}
                            tickFormatter={(value: number) => `${(value * 100).toFixed(0)}%`}
                            domain={['auto', 'auto']}
                        />
                        <ReferenceLine y={0} stroke="rgba(90, 150, 90, 0.32)" />
                        <Tooltip
                            content={<GrossPerformanceTooltip />}
                            cursor={{ stroke: '#517051', strokeWidth: 1, strokeDasharray: '4 4' }}
                        />
                        <Line
                            type="linear"
                            dataKey="portfolioGross"
                            name={`${periodLabel} portfolio gross`}
                            stroke="#33ff33"
                            strokeWidth={2.5}
                            dot={false}
                            activeDot={{ r: 4, fill: '#33ff33', stroke: '#040704', strokeWidth: 2 }}
                            isAnimationActive={false}
                        />
                        {/* Monochrome leaves only brightness and stroke pattern to separate
                            series. The portfolio stays the bright solid line because it is the
                            subject; the benchmark is dimmer and dashed, so a same-hue pair never
                            reads as one thick line. */}
                        <Line
                            type="linear"
                            dataKey="benchmark"
                            name="S&P 500"
                            stroke="#1f9e1f"
                            strokeWidth={1.75}
                            strokeDasharray="3 3"
                            dot={false}
                            activeDot={{ r: 4, fill: '#1f9e1f', stroke: '#040704', strokeWidth: 2 }}
                            isAnimationActive={false}
                        />
                        <Line
                            type="linear"
                            dataKey="spread"
                            name="Spread"
                            stroke="#ffc70f"
                            strokeWidth={1.75}
                            strokeDasharray="6 5"
                            dot={false}
                            activeDot={{ r: 4, fill: '#ffc70f', stroke: '#040704', strokeWidth: 2 }}
                            isAnimationActive={false}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
};

interface BookContributionPoint {
    date: string;
    longContribution: number;
    shortContribution: number;
    total: number;
}

const BookContributionTooltip = ({ active, payload, label }: {
    active?: boolean;
    payload?: Array<{ payload?: BookContributionPoint }>;
    label?: string;
}) => {
    const point = payload?.[0]?.payload;
    if (!active || !point) return null;

    return (
        <div className="min-w-[220px] rounded-lg border border-white/10 bg-slate-950/95 p-3 shadow-2xl">
            <div className="mb-3 font-mono text-[11px] font-semibold text-gray-400">
                {formatDate(label ?? point.date)}
            </div>
            <div className="space-y-2 font-mono text-xs tabular-nums">
                <div className="flex items-center justify-between gap-5">
                    <span className="flex items-center gap-2 text-gray-400">
                        <span className="h-2 w-2 rounded-full bg-emerald-400" /> Long book
                    </span>
                    <span className="font-bold text-emerald-300">{formatSignedPercent(point.longContribution, 2)}</span>
                </div>
                <div className="flex items-center justify-between gap-5">
                    <span className="flex items-center gap-2 text-gray-400">
                        <span className="h-2 w-2 rounded-full bg-rose-400" /> Short book
                    </span>
                    <span className="font-bold text-rose-300">{formatSignedPercent(point.shortContribution, 2)}</span>
                </div>
                <div className="flex items-center justify-between gap-5 border-t border-white/[0.08] pt-2">
                    <span className="flex items-center gap-2 text-gray-400">
                        <span className="h-0 w-3 border-t-2 border-dashed border-slate-300" /> Combined gross
                    </span>
                    <span className="font-bold text-slate-200">{formatSignedPercent(point.total, 2)}</span>
                </div>
            </div>
        </div>
    );
};

const BookContributionChart = ({ data, periodLabel }: { data: BookContributionPoint[]; periodLabel: string }) => {
    if (!data.length) {
        return (
            <div className="rounded-lg border border-white/[0.07] bg-slate-950/70 p-5 text-sm text-gray-500">
                Long/short book contribution needs the dated rebalance engine; it will appear once segmented history is available.
            </div>
        );
    }

    const latest = data[data.length - 1];

    return (
        <div className="rounded-lg border border-white/[0.07] bg-slate-950/70 p-4 shadow-lg shadow-black/20 sm:p-5">
            <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                    <div className="flex items-center gap-2">
                        <ChartNoAxesCombined className="h-4 w-4 shrink-0 text-emerald-300" />
                        <h3 className="text-[11px] font-bold uppercase tracking-[0.16em] text-gray-300">
                            Long Book vs Short Book Contribution
                        </h3>
                    </div>
                    <p className="mt-1 text-[11px] text-gray-500">
                        Cumulative gross contribution of each side to {periodLabel} return. Sides are side-adjusted, so a
                        rising short reads as a loss; the two add up to combined gross.
                    </p>
                </div>
                <div className="grid grid-cols-3 gap-x-5 gap-y-2 font-mono text-[11px] tabular-nums sm:flex sm:flex-wrap sm:justify-end">
                    <div>
                        <div className="mb-1 flex items-center gap-1.5 text-[9px] uppercase tracking-[0.12em] text-gray-500">
                            <span className="h-2 w-2 rounded-full bg-emerald-400" /> Long book
                        </div>
                        <div className="font-bold text-emerald-300">{formatSignedPercent(latest.longContribution)}</div>
                    </div>
                    <div>
                        <div className="mb-1 flex items-center gap-1.5 text-[9px] uppercase tracking-[0.12em] text-gray-500">
                            <span className="h-2 w-2 rounded-full bg-rose-400" /> Short book
                        </div>
                        <div className="font-bold text-rose-300">{formatSignedPercent(latest.shortContribution)}</div>
                    </div>
                    <div>
                        <div className="mb-1 flex items-center gap-1.5 text-[9px] uppercase tracking-[0.12em] text-gray-500">
                            <span className="h-0 w-3 border-t-2 border-dashed border-slate-300" /> Combined
                        </div>
                        <div className="font-bold text-slate-200">{formatSignedPercent(latest.total)}</div>
                    </div>
                </div>
            </div>

            <div className="h-[270px] w-full sm:h-[320px]">
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                        <CartesianGrid vertical={false} stroke="rgba(90, 150, 90, 0.10)" />
                        <XAxis
                            dataKey="date"
                            axisLine={false}
                            tickLine={false}
                            minTickGap={42}
                            tick={{ fill: '#517051', fontSize: 10, fontFamily: 'monospace' }}
                            tickFormatter={(value: string) => formatDate(value, false)}
                        />
                        <YAxis
                            axisLine={false}
                            tickLine={false}
                            width={48}
                            tick={{ fill: '#517051', fontSize: 10, fontFamily: 'monospace' }}
                            tickFormatter={(value: number) => `${(value * 100).toFixed(0)}%`}
                            domain={['auto', 'auto']}
                        />
                        <ReferenceLine y={0} stroke="rgba(90, 150, 90, 0.32)" />
                        <Tooltip
                            content={<BookContributionTooltip />}
                            cursor={{ stroke: '#517051', strokeWidth: 1, strokeDasharray: '4 4' }}
                        />
                        <Line
                            type="linear"
                            dataKey="longContribution"
                            name="Long book"
                            stroke="#33ff33"
                            strokeWidth={2.5}
                            dot={false}
                            activeDot={{ r: 4, fill: '#33ff33', stroke: '#040704', strokeWidth: 2 }}
                            isAnimationActive={false}
                        />
                        <Line
                            type="linear"
                            dataKey="shortContribution"
                            name="Short book"
                            stroke="#ff770f"
                            strokeWidth={2.5}
                            dot={false}
                            activeDot={{ r: 4, fill: '#ff770f', stroke: '#040704', strokeWidth: 2 }}
                            isAnimationActive={false}
                        />
                        <Line
                            type="linear"
                            dataKey="total"
                            name="Combined gross"
                            stroke="#a3c2a3"
                            strokeWidth={1.75}
                            strokeDasharray="6 5"
                            dot={false}
                            activeDot={{ r: 4, fill: '#a3c2a3', stroke: '#040704', strokeWidth: 2 }}
                            isAnimationActive={false}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
};

interface HistoricalDiagnosticsProps {
    data: AnalyticsHistoryPoint[];
    performance: HistoryPoint[];
    periodLabel?: string;
}

export const HistoricalDiagnostics: React.FC<HistoricalDiagnosticsProps> = React.memo(({
    data,
    performance,
    periodLabel = 'YTD',
}) => {
    const points = data.map(point => ({
        ...point,
        beta: clean(point.beta),
        volatility: clean(point.volatility),
        drawdown: clean(point.drawdown),
        battingAverage: clean(point.battingAverage),
        variance: clean(point.variance),
    }));

    const performancePoints = performance.flatMap((point): GrossPerformancePoint[] => {
        const gross = clean(point.portfolioGross);
        const benchmark = clean(point.benchmark);
        if (gross === null || benchmark === null || gross <= 0 || benchmark <= 0) return [];

        const portfolioReturn = gross / 100000 - 1;
        const benchmarkReturn = benchmark / 100000 - 1;
        return [{
            date: point.date,
            portfolioGross: portfolioReturn,
            benchmark: benchmarkReturn,
            spread: portfolioReturn - benchmarkReturn,
        }];
    });

    // The backend only emits these two series from the segmented (dated-rebalance)
    // engine, so a missing value means "not computed", not "zero". Drop those dates
    // rather than drawing a flat line the accounting never produced.
    const bookContributionPoints = data.flatMap((point): BookContributionPoint[] => {
        const longContribution = clean(point.longContribution);
        const shortContribution = clean(point.shortContribution);
        if (longContribution === null || shortContribution === null) return [];
        return [{
            date: point.date,
            longContribution,
            shortContribution,
            total: longContribution + shortContribution,
        }];
    });

    if (!points.length && !performancePoints.length) return null;

    const latest = points[points.length - 1];
    const worstDrawdown = points.reduce((min, point) => {
        const value = clean(point.drawdown);
        return value === null ? min : Math.min(min, value);
    }, 0);
    const firstDate = performancePoints[0]?.date ?? points[0]?.date;
    const lastDate = performancePoints[performancePoints.length - 1]?.date ?? latest?.date;

    return (
        <section className="rounded-lg border border-white/[0.06] bg-gradient-to-b from-slate-900/55 to-slate-950/70 p-4 sm:p-5">
            <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <h2 className="text-sm font-black uppercase tracking-[0.18em] text-gray-300">Historical Diagnostics</h2>
                    <p className="text-xs text-gray-500">{periodLabel} risk, drawdown, and gross performance path</p>
                </div>
                <div className="font-mono text-[11px] text-gray-500">
                    {firstDate && lastDate ? `${formatDate(firstDate)} to ${formatDate(lastDate)}` : null}
                </div>
            </div>

            {latest && (
                <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
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
                        // The headline, the plotted series and the formatter are all
                        // annualised volatility. Daily variance is ~1000x smaller and is
                        // reported in the subtitle, so the title has to say volatility.
                        title="Volatility (ann.)"
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
                </div>
            )}

            <GrossPerformanceChart data={performancePoints} periodLabel={periodLabel} />

            {bookContributionPoints.length > 0 && (
                <BookContributionChart data={bookContributionPoints} periodLabel={periodLabel} />
            )}
        </section>
    );
});
