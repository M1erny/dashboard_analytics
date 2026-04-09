import React, { useRef, useEffect } from 'react';
import type { ConvexityMetrics, StressTest } from '../../utils/finance';
import { cn } from '../../lib/utils';
import { ArrowUpRight, ArrowDownRight, TrendingUp, Zap, Activity } from 'lucide-react';

interface ConvexityWidgetProps {
    convexity?: ConvexityMetrics | null;
    stressTests?: StressTest[];
}

// ─── Formatters ──────────────────────────────────────────────
const fmtPct = (val: number | undefined, decimals = 1) =>
    typeof val === 'number' ? `${(val * 100).toFixed(decimals)}%` : 'N/A';

const fmtSignedPct = (val: number | undefined, decimals = 2) => {
    if (typeof val !== 'number') return 'N/A';
    const sign = val > 0 ? '+' : '';
    return `${sign}${(val * 100).toFixed(decimals)}%`;
};

const fmtNum = (val: number | undefined, decimals = 2) =>
    typeof val === 'number' ? val.toFixed(decimals) : 'N/A';

// ─── Scatter Plot (Canvas + SVG tooltip overlay) ─────────────
interface ScatterPoint { date: string; bench: number; port: number; }

const ScatterPlot: React.FC<{
    data: [string, number, number][];
    coeffs: [number, number, number];
    linearCoeffs?: [number, number];
    rSquared: number;
}> = ({ data, coeffs, linearCoeffs, rSquared }) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const wrapperRef = useRef<HTMLDivElement>(null);
    const [tooltip, setTooltip] = React.useState<{ x: number; y: number; point: ScatterPoint } | null>(null);

    // Store the scale functions and point screen coords for hit-testing
    const hitRef = useRef<{
        points: { sx: number; sy: number; d: ScatterPoint }[];
    }>({ points: [] });

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas || !data.length) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        const w = rect.width;
        const h = rect.height;
        const padding = { top: 20, right: 20, bottom: 32, left: 40 };
        const plotW = w - padding.left - padding.right;
        const plotH = h - padding.top - padding.bottom;

        const benchVals = data.map(d => d[1]);
        const portVals  = data.map(d => d[2]);
        const maxAbsX = Math.max(Math.abs(Math.min(...benchVals)), Math.abs(Math.max(...benchVals))) * 1.1;
        const maxAbsY = Math.max(Math.abs(Math.min(...portVals)),  Math.abs(Math.max(...portVals)))  * 1.1;

        const scaleX = (v: number) => padding.left + (v + maxAbsX) / (2 * maxAbsX) * plotW;
        const scaleY = (v: number) => padding.top  + plotH - (v + maxAbsY) / (2 * maxAbsY) * plotH;

        // Background
        ctx.fillStyle = 'transparent';
        ctx.fillRect(0, 0, w, h);

        // Grid lines
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const x = padding.left + (plotW / 4) * i;
            const y = padding.top  + (plotH / 4) * i;
            ctx.beginPath(); ctx.moveTo(x, padding.top); ctx.lineTo(x, padding.top + plotH); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(padding.left + plotW, y); ctx.stroke();
        }

        // Zero axes
        ctx.strokeStyle = 'rgba(255,255,255,0.15)';
        ctx.lineWidth = 1;
        const zeroX = scaleX(0);
        const zeroY = scaleY(0);
        ctx.beginPath(); ctx.moveTo(zeroX, padding.top); ctx.lineTo(zeroX, padding.top + plotH); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(padding.left, zeroY); ctx.lineTo(padding.left + plotW, zeroY); ctx.stroke();

        // 45-degree reference line (β=1)
        ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(scaleX(-maxAbsX), scaleY(-maxAbsX));
        ctx.lineTo(scaleX(maxAbsX),  scaleY(maxAbsX));
        ctx.stroke();
        ctx.setLineDash([]);

        // Data points — store screen coords for hit-testing
        const screenPoints: { sx: number; sy: number; d: ScatterPoint }[] = [];
        for (const [date, bx, py] of data) {
            const sx = scaleX(bx);
            const sy = scaleY(py);
            const isGoodOutcome = (bx > 0 && py > 0) || (bx < 0 && py > bx);
            ctx.fillStyle = isGoodOutcome ? 'rgba(52, 211, 153, 0.4)' : 'rgba(251, 113, 133, 0.4)';
            ctx.beginPath();
            ctx.arc(sx, sy, 3, 0, Math.PI * 2);
            ctx.fill();
            screenPoints.push({ sx, sy, d: { date, bench: bx, port: py } });
        }
        hitRef.current.points = screenPoints;

        // Linear regression line
        if (linearCoeffs) {
            const [linB, linA] = linearCoeffs;
            ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(scaleX(-maxAbsX), scaleY(linA + linB * -maxAbsX));
            ctx.lineTo(scaleX(maxAbsX),  scaleY(linA + linB * maxAbsX));
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // Quadratic regression curve
        const [b2, b1, a] = coeffs;
        ctx.strokeStyle = '#fbbf24';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        const steps = 100;
        for (let i = 0; i <= steps; i++) {
            const x  = -maxAbsX + (2 * maxAbsX * i) / steps;
            const y  = a + b1 * x + b2 * x * x;
            const sx = scaleX(x);
            const sy = scaleY(y);
            if (i === 0) ctx.moveTo(sx, sy);
            else         ctx.lineTo(sx, sy);
        }
        ctx.stroke();

        // Axis labels
        ctx.fillStyle = 'rgba(156, 163, 175, 0.7)';
        ctx.font = '10px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('SPY Daily Return →', w / 2, h - 4);
        ctx.save();
        ctx.translate(10, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('Portfolio Return →', 0, 0);
        ctx.restore();

        // R² annotation
        ctx.fillStyle = 'rgba(251, 191, 36, 0.7)';
        ctx.font = 'bold 10px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`R² = ${rSquared.toFixed(3)}`, w - padding.right - 4, padding.top + 14);
        ctx.fillText(`β₂ = ${b2.toFixed(4)}`,       w - padding.right - 4, padding.top + 28);

    }, [data, coeffs, linearCoeffs, rSquared]);

    const handleMouseMove = React.useCallback((e: React.MouseEvent<HTMLDivElement>) => {
        const wrapper = wrapperRef.current;
        if (!wrapper) return;
        const rect = wrapper.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        const pts = hitRef.current.points;
        let closest: typeof pts[0] | null = null;
        let closestDist = Infinity;
        for (const p of pts) {
            const dist = Math.sqrt((p.sx - mx) ** 2 + (p.sy - my) ** 2);
            if (dist < closestDist) { closestDist = dist; closest = p; }
        }

        if (closest && closestDist < 20) {
            setTooltip({ x: closest.sx, y: closest.sy, point: closest.d });
        } else {
            setTooltip(null);
        }
    }, []);

    const handleMouseLeave = React.useCallback(() => setTooltip(null), []);

    const fmtTip = (v: number) => {
        const sign = v > 0 ? '+' : '';
        return `${sign}${(v * 100).toFixed(2)}%`;
    };

    return (
        <div
            ref={wrapperRef}
            className="relative w-full select-none"
            style={{ height: '240px' }}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
        >
            <canvas ref={canvasRef} className="absolute inset-0 w-full h-full rounded-lg" />

            {tooltip && (
                <div
                    className="pointer-events-none absolute z-20"
                    style={{
                        left: tooltip.x + (tooltip.x > 160 ? -148 : 12),
                        top:  tooltip.y + (tooltip.y > 160 ? -100 : 8),
                        transform: 'translateZ(0)',
                    }}
                >
                    <div
                        className="rounded-xl border border-white/10 px-3 py-2.5 text-xs font-mono shadow-xl"
                        style={{
                            background: 'rgba(15, 23, 42, 0.92)',
                            backdropFilter: 'blur(12px)',
                            minWidth: '136px',
                        }}
                    >
                        <div className="text-gray-400 text-[10px] uppercase tracking-widest mb-1.5 font-semibold">
                            {tooltip.point.date}
                        </div>
                        <div className="flex justify-between gap-4 items-center">
                            <span className="text-gray-500 text-[10px]">Portfolio</span>
                            <span className={`font-black text-sm ${tooltip.point.port >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                {fmtTip(tooltip.point.port)}
                            </span>
                        </div>
                        <div className="flex justify-between gap-4 items-center mt-0.5">
                            <span className="text-gray-500 text-[10px]">SPY</span>
                            <span className={`font-black text-sm ${tooltip.point.bench >= 0 ? 'text-sky-400' : 'text-orange-400'}`}>
                                {fmtTip(tooltip.point.bench)}
                            </span>
                        </div>
                        <div className="mt-1.5 pt-1.5 border-t border-white/[0.07] flex justify-between items-center">
                            <span className="text-gray-600 text-[9px]">Spread</span>
                            <span className={`text-[10px] font-bold ${(tooltip.point.port - tooltip.point.bench) >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                                {fmtTip(tooltip.point.port - tooltip.point.bench)}
                            </span>
                        </div>
                    </div>
                </div>
            )}

            {/* Crosshair dot on hovered point */}
            {tooltip && (
                <div
                    className="pointer-events-none absolute z-10 rounded-full ring-2 ring-white/40"
                    style={{
                        width: 10, height: 10,
                        left: tooltip.x - 5,
                        top:  tooltip.y - 5,
                        background: tooltip.point.port >= 0 ? 'rgba(52,211,153,0.9)' : 'rgba(251,113,133,0.9)',
                    }}
                />
            )}
        </div>
    );
};


// ─── Main Component ──────────────────────────────────────────
export const ConvexityWidget: React.FC<ConvexityWidgetProps> = ({ convexity, stressTests }) => {
    if (!convexity) return null;

    const { upsideCapture, downsideCapture, captureSpread, quadraticCoeffs, rSquared, isConvex, scatterData } = convexity;

    const spreadPositive = (captureSpread ?? 0) > 0;

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">

                {/* ── LEFT: Capture Ratios Card ── */}
                <div className={cn(
                    "lg:col-span-4 rounded-xl border p-5 backdrop-blur-xl",
                    "bg-gradient-to-br",
                    spreadPositive
                        ? "border-emerald-500/20 from-emerald-950/20 via-slate-900/90 to-slate-950"
                        : "border-rose-500/20 from-rose-950/20 via-slate-900/90 to-slate-950"
                )}>
                    <div className="flex items-center gap-2 mb-4">
                        <div className={cn(
                            "flex items-center justify-center w-7 h-7 rounded-lg",
                            spreadPositive ? "bg-emerald-500/15 text-emerald-400" : "bg-rose-500/15 text-rose-400"
                        )}>
                            <Activity className="h-4 w-4" />
                        </div>
                        <span className="text-[11px] text-gray-400 uppercase tracking-[0.15em] font-semibold">
                            Convexity Profile
                        </span>
                    </div>

                    {/* Capture Spread (hero) */}
                    <div className="mb-4">
                        <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Capture Spread</span>
                        <div className="flex items-end gap-2 mt-1">
                            <span className={cn(
                                "text-3xl font-black tracking-tighter leading-none",
                                spreadPositive ? "text-emerald-400" : "text-rose-400"
                            )}>
                                {fmtSignedPct(captureSpread)}
                            </span>
                            <span className={cn(
                                "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border mb-0.5",
                                spreadPositive
                                    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                                    : "bg-rose-500/10 text-rose-400 border-rose-500/20"
                            )}>
                                {spreadPositive ? 'Convex' : 'Concave'}
                            </span>
                        </div>
                    </div>

                    {/* Upside / Downside Capture */}
                    <div className="space-y-2">
                        <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
                            <div className="flex items-center gap-2">
                                <span className="flex items-center justify-center w-5 h-5 rounded bg-emerald-500/15">
                                    <ArrowUpRight className="h-3 w-3 text-emerald-400" />
                                </span>
                                <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider">Upside</span>
                            </div>
                            <span className={cn(
                                "font-mono text-lg font-black tracking-tight",
                                (upsideCapture ?? 0) > 1 ? "text-emerald-400" : "text-gray-400"
                            )}>
                                {fmtPct(upsideCapture, 0)}
                            </span>
                        </div>
                        <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]">
                            <div className="flex items-center gap-2">
                                <span className="flex items-center justify-center w-5 h-5 rounded bg-rose-500/15">
                                    <ArrowDownRight className="h-3 w-3 text-rose-400" />
                                </span>
                                <span className="text-xs text-gray-400 font-semibold uppercase tracking-wider">Downside</span>
                            </div>
                            <span className={cn(
                                "font-mono text-lg font-black tracking-tight",
                                (downsideCapture ?? 0) < 1 ? "text-emerald-400" : "text-rose-400"
                            )}>
                                {fmtPct(downsideCapture, 0)}
                            </span>
                        </div>
                    </div>

                    {/* Visual bar: upside vs downside */}
                    <div className="flex items-center gap-1 mt-3">
                        <div className="flex-1 h-2 rounded-l-full bg-emerald-500/20 overflow-hidden">
                            <div className="h-full bg-emerald-500/60 rounded-l-full transition-all duration-700"
                                style={{ width: `${Math.min((upsideCapture ?? 0) * 50, 100)}%` }} />
                        </div>
                        <div className="w-px h-3 bg-white/20" />
                        <div className="flex-1 h-2 rounded-r-full bg-rose-500/20 overflow-hidden flex justify-end">
                            <div className="h-full bg-rose-500/60 rounded-r-full transition-all duration-700"
                                style={{ width: `${Math.min((downsideCapture ?? 0) * 50, 100)}%` }} />
                        </div>
                    </div>

                    <p className="text-[10px] text-gray-600 mt-3 leading-relaxed">
                        <strong className="text-gray-500">Convex payoff:</strong> Upside capture &gt; Downside capture.
                        Portfolio gains more when SPY is up and loses less when SPY is down.
                    </p>
                </div>

                {/* ── CENTER: Scatter Plot ── */}
                <div className="lg:col-span-5 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl">
                    <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                            <TrendingUp className="h-4 w-4 text-amber-400" />
                            <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">
                                Return Scatter + Regression
                            </span>
                        </div>
                        <span className={cn(
                            "text-[9px] font-mono px-2 py-0.5 rounded border",
                            isConvex
                                ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                                : "text-rose-400 bg-rose-500/10 border-rose-500/20"
                        )}>
                            β₂={fmtNum(quadraticCoeffs?.[0], 4)} {isConvex ? '↗ Convex' : '↘ Concave'}
                        </span>
                    </div>

                    {scatterData && scatterData.length > 0 ? (
                        <ScatterPlot
                            data={scatterData}
                            coeffs={quadraticCoeffs}
                            linearCoeffs={convexity.linearCoeffs}
                            rSquared={rSquared}
                        />
                    ) : (
                        <div className="flex items-center justify-center h-[240px] text-sm text-gray-600">
                            No scatter data available
                        </div>
                    )}

                    <p className="text-[10px] text-gray-600 mt-2 leading-relaxed">
                        <span className="text-amber-400/70">━</span> Quadratic fit &nbsp;·&nbsp;
                        <span className="text-slate-400/70">┄┄</span> Linear fit &nbsp;·&nbsp;
                        <span className="text-gray-500/40">┄┄</span> β=1 reference &nbsp;·&nbsp;
                        <span className="text-emerald-400/60">●</span> Favorable &nbsp;
                        <span className="text-rose-400/60">●</span> Unfavorable
                    </p>
                </div>

                {/* ── RIGHT: Non-Linear Stress Tests ── */}
                <div className="lg:col-span-3 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl">
                    <div className="flex items-center gap-2 mb-3">
                        <Zap className="h-4 w-4 text-violet-400" />
                        <span className="text-[11px] text-gray-400 uppercase tracking-[0.12em] font-semibold">
                            Stress Tests
                        </span>
                    </div>
                    <div className="text-[9px] text-gray-600 font-mono mb-3 px-2 py-1 rounded bg-white/[0.03] border border-white/[0.05]">
                        Quadratic model (non-linear)
                    </div>

                    <div className="space-y-2">
                        {stressTests?.map(st => {
                            const isDownside = (st.marketMove ?? st.impact) < 0;
                            const diff = (st.linearImpact != null) ? st.impact - st.linearImpact : 0;
                            const convexBenefit = isDownside ? diff > 0 : diff > 0; // positive diff = better than linear

                            return (
                                <div key={st.scenario}
                                    className="rounded-lg bg-white/[0.03] px-3 py-2.5 border border-white/[0.05]"
                                >
                                    <div className="flex justify-between items-center">
                                        <span className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider truncate mr-2">
                                            {st.scenario.replace(/\(.*?\)/, '').trim()}
                                        </span>
                                        <span className={cn(
                                            "font-mono text-sm font-black tracking-tight whitespace-nowrap",
                                            st.impact >= 0 ? "text-emerald-400" : "text-rose-400"
                                        )}>
                                            {fmtSignedPct(st.impact)}
                                        </span>
                                    </div>

                                    {/* Linear comparison */}
                                    {st.linearImpact != null && Math.abs(diff) > 0.0001 && (
                                        <div className="flex justify-between items-center mt-1">
                                            <span className="text-[9px] text-gray-600">
                                                vs linear
                                            </span>
                                            <span className={cn(
                                                "font-mono text-[10px] font-semibold",
                                                convexBenefit ? "text-emerald-500/70" : "text-rose-500/70"
                                            )}>
                                                {fmtSignedPct(st.linearImpact)} ({convexBenefit ? '▲' : '▼'}{Math.abs(diff * 100).toFixed(2)}pp)
                                            </span>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    <p className="text-[10px] text-gray-600 mt-3 leading-relaxed">
                        Long/short + AFRM creates non-linear payoff. Linear β model overstates downside.
                    </p>
                </div>
            </div>
        </div>
    );
};
