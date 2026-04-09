import React, { useRef, useEffect } from 'react';
import type { ConvexityMetrics, ScatterDataPoint } from '../../utils/finance';
import { cn } from '../../lib/utils';
import { ArrowUpRight, ArrowDownRight, TrendingUp, Activity } from 'lucide-react';

interface ConvexityWidgetProps {
    convexity?: ConvexityMetrics | null;
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

// ─── Scatter Plot ─────────────────────────────────────────────

const ScatterPlot: React.FC<{
    data: ScatterDataPoint[];
    coeffs: [number, number, number];
    linearCoeffs?: [number, number];
    rSquared: number;
}> = ({ data, coeffs, linearCoeffs, rSquared }) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const wrapperRef = useRef<HTMLDivElement>(null);
    const [tooltip, setTooltip] = React.useState<{
        x: number; y: number; point: ScatterDataPoint; flipX: boolean; flipY: boolean;
    } | null>(null);

    const hitRef = useRef<{ sx: number; sy: number; pt: ScatterDataPoint }[]>([]);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas || !data.length) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width  = rect.width  * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        const w = rect.width, h = rect.height;
        const pad = { top: 20, right: 20, bottom: 32, left: 40 };
        const plotW = w - pad.left - pad.right;
        const plotH = h - pad.top  - pad.bottom;

        const maxAbsX = Math.max(...data.map(d => Math.abs(d.b))) * 1.1;
        const maxAbsY = Math.max(...data.map(d => Math.abs(d.p))) * 1.1;

        const sx = (v: number) => pad.left  + (v + maxAbsX) / (2 * maxAbsX) * plotW;
        const sy = (v: number) => pad.top + plotH - (v + maxAbsY) / (2 * maxAbsY) * plotH;

        // Grid
        ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const gx = pad.left + (plotW / 4) * i;
            const gy = pad.top  + (plotH / 4) * i;
            ctx.beginPath(); ctx.moveTo(gx, pad.top);  ctx.lineTo(gx, pad.top + plotH); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(pad.left + plotW, gy); ctx.stroke();
        }

        // Zero axes
        ctx.strokeStyle = 'rgba(255,255,255,0.15)'; ctx.lineWidth = 1;
        const zx = sx(0), zy = sy(0);
        ctx.beginPath(); ctx.moveTo(zx, pad.top);  ctx.lineTo(zx, pad.top + plotH); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(pad.left, zy); ctx.lineTo(pad.left + plotW, zy); ctx.stroke();

        // β=1 reference
        ctx.strokeStyle = 'rgba(255,255,255,0.08)'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(sx(-maxAbsX), sy(-maxAbsX)); ctx.lineTo(sx(maxAbsX), sy(maxAbsX)); ctx.stroke();
        ctx.setLineDash([]);

        // Data points
        const hits: typeof hitRef.current = [];
        for (const pt of data) {
            const px = sx(pt.b), py = sy(pt.p);
            const good = (pt.b > 0 && pt.p > 0) || (pt.b < 0 && pt.p > pt.b);
            ctx.fillStyle = good ? 'rgba(52,211,153,0.45)' : 'rgba(251,113,133,0.45)';
            ctx.beginPath(); ctx.arc(px, py, 3, 0, Math.PI * 2); ctx.fill();
            hits.push({ sx: px, sy: py, pt });
        }
        hitRef.current = hits;

        // Linear fit
        if (linearCoeffs) {
            const [lb, la] = linearCoeffs;
            ctx.strokeStyle = 'rgba(148,163,184,0.4)'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(sx(-maxAbsX), sy(la + lb * -maxAbsX));
            ctx.lineTo(sx(maxAbsX),  sy(la + lb *  maxAbsX));
            ctx.stroke(); ctx.setLineDash([]);
        }

        // Quadratic fit
        const [b2, b1, a] = coeffs;
        ctx.strokeStyle = '#fbbf24'; ctx.lineWidth = 2.5; ctx.beginPath();
        for (let i = 0; i <= 120; i++) {
            const xv = -maxAbsX + (2 * maxAbsX * i) / 120;
            const yv = a + b1 * xv + b2 * xv * xv;
            i === 0 ? ctx.moveTo(sx(xv), sy(yv)) : ctx.lineTo(sx(xv), sy(yv));
        }
        ctx.stroke();

        // Axis labels
        ctx.fillStyle = 'rgba(156,163,175,0.7)'; ctx.font = '10px monospace'; ctx.textAlign = 'center';
        ctx.fillText('SPY Daily Return →', w / 2, h - 4);
        ctx.save(); ctx.translate(10, h / 2); ctx.rotate(-Math.PI / 2);
        ctx.fillText('Portfolio Return →', 0, 0); ctx.restore();

        // Annotations
        ctx.fillStyle = 'rgba(251,191,36,0.7)'; ctx.font = 'bold 10px monospace'; ctx.textAlign = 'right';
        ctx.fillText(`R² = ${rSquared.toFixed(3)}`, w - pad.right - 4, pad.top + 14);
        ctx.fillText(`β₂ = ${b2.toFixed(4)}`,       w - pad.right - 4, pad.top + 28);

    }, [data, coeffs, linearCoeffs, rSquared]);

    const handleMouseMove = React.useCallback((e: React.MouseEvent<HTMLDivElement>) => {
        const wrapper = wrapperRef.current;
        if (!wrapper) return;
        const rect   = wrapper.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const hits = hitRef.current;
        let best: typeof hits[0] | null = null, bestD = Infinity;
        for (const h of hits) {
            const d = Math.sqrt((h.sx - mx) ** 2 + (h.sy - my) ** 2);
            if (d < bestD) { bestD = d; best = h; }
        }
        if (best && bestD < 22) {
            setTooltip({ 
                x: best.sx, y: best.sy, point: best.pt, 
                flipX: best.sx > rect.width * 0.6, 
                flipY: best.sy > rect.height * 0.6 
            });
        }
        else setTooltip(null);
    }, []);

    const handleMouseLeave = React.useCallback(() => setTooltip(null), []);

    const sp  = (v: number, d = 2) => `${v > 0 ? '+' : ''}${(v * 100).toFixed(d)}%`;

    return (
        <div
            ref={wrapperRef}
            className="relative w-full select-none cursor-crosshair"
            style={{ height: '240px' }}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
        >
            <canvas ref={canvasRef} className="absolute inset-0 w-full h-full rounded-lg" />

            {/* ── Crosshair highlight dot ── */}
            {tooltip && (
                <div
                    className="pointer-events-none absolute z-10 rounded-full ring-2 ring-white/50 animate-pulse"
                    style={{
                        width: 11, height: 11,
                        left: tooltip.x - 5.5, top: tooltip.y - 5.5,
                        background: tooltip.point.p >= 0 ? 'rgba(52,211,153,0.95)' : 'rgba(251,113,133,0.95)',
                    }}
                />
            )}

            {/* ── Tooltip ── */}
            {tooltip && (
                <div
                    className="pointer-events-none absolute z-[100]"
                    style={{ 
                        left: tooltip.x, 
                        top: tooltip.y,
                        transform: `translate(${tooltip.flipX ? 'calc(-100% - 14px)' : '14px'}, ${tooltip.flipY ? 'calc(-100% - 14px)' : '14px'})`,
                        transition: 'transform 0.1s ease-out'
                    }}
                >
                    <div
                        className="rounded-2xl border border-white/[0.09] shadow-2xl overflow-hidden"
                        style={{
                            background: 'rgba(10, 15, 30, 0.96)',
                            backdropFilter: 'blur(20px)',
                            width: '222px',
                        }}
                    >
                        {/* Date header */}
                        <div className="px-3.5 pt-3 pb-2 border-b border-white/[0.06]">
                            <div className="text-[10px] text-sky-400/80 uppercase tracking-[0.18em] font-bold mb-1">
                                {tooltip.point.d}
                            </div>
                            <div className="flex justify-between items-end">
                                <div>
                                    <div className="text-[9px] text-gray-500 mb-0.5">Portfolio</div>
                                    <div className={`text-lg font-black tracking-tight leading-none ${tooltip.point.p >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {sp(tooltip.point.p)}
                                    </div>
                                </div>
                                <div className="text-right">
                                    <div className="text-[9px] text-gray-500 mb-0.5">vs SPY</div>
                                    <div className={`text-lg font-black tracking-tight leading-none ${tooltip.point.b >= 0 ? 'text-sky-400' : 'text-orange-400'}`}>
                                        {sp(tooltip.point.b)}
                                    </div>
                                </div>
                            </div>
                            {/* Spread bar */}
                            <div className="mt-2 flex justify-between items-center">
                                <span className="text-[9px] text-gray-600">α-spread</span>
                                <span className={`text-[10px] font-bold ${(tooltip.point.p - tooltip.point.b) >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                                    {sp(tooltip.point.p - tooltip.point.b)}
                                </span>
                            </div>
                        </div>

                        {/* Contributors */}
                        <div className="px-3.5 py-2.5">
                            <div className="text-[9px] text-gray-600 uppercase tracking-widest font-bold mb-2">
                                Daily Drivers
                            </div>

                            {/* Top contributors */}
                            {tooltip.point.top.length > 0 && (
                                <div className="space-y-1 mb-2">
                                    {tooltip.point.top.map(c => (
                                        <div key={c.t} className="flex items-center gap-2">
                                            <div className="w-1 h-4 rounded-full bg-emerald-500/60 flex-shrink-0" />
                                            <span className="text-[10px] font-bold text-gray-300 w-12 flex-shrink-0 font-mono">{c.t}</span>
                                            <div className="flex-1 flex justify-between items-center gap-1">
                                                <span className="text-[9px] text-gray-500 font-mono">{sp(c.r)} stk</span>
                                                <span className="text-[10px] font-black text-emerald-400 font-mono">{sp(c.c)}</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {/* Divider if both sides exist */}
                            {tooltip.point.top.length > 0 && tooltip.point.bot.length > 0 && (
                                <div className="border-t border-white/[0.05] my-1.5" />
                            )}

                            {/* Bottom contributors */}
                            {tooltip.point.bot.length > 0 && (
                                <div className="space-y-1">
                                    {tooltip.point.bot.map(c => (
                                        <div key={c.t} className="flex items-center gap-2">
                                            <div className="w-1 h-4 rounded-full bg-rose-500/60 flex-shrink-0" />
                                            <span className="text-[10px] font-bold text-gray-300 w-12 flex-shrink-0 font-mono">{c.t}</span>
                                            <div className="flex-1 flex justify-between items-center gap-1">
                                                <span className="text-[9px] text-gray-500 font-mono">{sp(c.r)} stk</span>
                                                <span className="text-[10px] font-black text-rose-400 font-mono">{sp(c.c)}</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {tooltip.point.top.length === 0 && tooltip.point.bot.length === 0 && (
                                <div className="text-[9px] text-gray-700 italic">No contributor data</div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};


// ─── Main Component ──────────────────────────────────────────
export const ConvexityWidget: React.FC<ConvexityWidgetProps> = ({ convexity }) => {
    if (!convexity) return null;

    const { upsideCapture, downsideCapture, captureSpread, quadraticCoeffs, rSquared, isConvex, scatterData } = convexity;

    const spreadPositive = (captureSpread ?? 0) > 0;

    return (
        <div className="space-y-4 relative z-20">
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
                <div className="lg:col-span-8 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 backdrop-blur-xl">
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

            </div>
        </div>
    );
};
