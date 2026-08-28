import React, { useLayoutEffect, useRef, useState, memo } from 'react';
import { createPortal } from 'react-dom';
import { Globe2 } from 'lucide-react';
import {
    ComposableMap,
    Geographies,
    Geography,
    ZoomableGroup
} from 'react-simple-maps';

const geoUrl = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

const COUNTRY_NAMES: Record<string, string> = {
    'United States of America': 'USA',
    'Poland': 'POL',
    'Netherlands': 'NLD',
    'Finland': 'FIN',
    'Japan': 'JPN',
    'South Korea': 'KOR',
    'Portugal': 'PRT',
    'Denmark': 'DNK',
    'Belgium': 'BEL',
    'Canada': 'CAN',
};

interface CountryAllocation {
    long: number;
    short: number;
    contribution: number;
    tickers: { ticker: string; weight: number; type: string; contribution: number }[];
}

interface CountryMapWidgetProps {
    countryAllocation?: Record<string, CountryAllocation>;
}

export const CountryMapWidget: React.FC<CountryMapWidgetProps> = memo(({ countryAllocation }) => {
    const [tooltipContent, setTooltipContent] = useState<{ name: string; data: CountryAllocation } | null>(null);
    const [tooltipAnchor, setTooltipAnchor] = useState({ x: 0, y: 0 });
    const [tooltipPos, setTooltipPos] = useState<{ left: number; top: number } | null>(null);
    const tooltipRef = useRef<HTMLDivElement>(null);

    useLayoutEffect(() => {
        if (!tooltipContent || !tooltipRef.current) return;

        const positionTooltip = () => {
            const tooltip = tooltipRef.current;
            if (!tooltip) return;

            const rect = tooltip.getBoundingClientRect();
            const viewportPadding = 12;
            const cursorGap = 16;
            const roomOnRight = tooltipAnchor.x + cursorGap + rect.width <= window.innerWidth - viewportPadding;
            const preferredLeft = roomOnRight
                ? tooltipAnchor.x + cursorGap
                : tooltipAnchor.x - cursorGap - rect.width;
            const maxLeft = Math.max(viewportPadding, window.innerWidth - rect.width - viewportPadding);
            const maxTop = Math.max(viewportPadding, window.innerHeight - rect.height - viewportPadding);

            setTooltipPos({
                left: Math.min(Math.max(preferredLeft, viewportPadding), maxLeft),
                top: Math.min(Math.max(tooltipAnchor.y - rect.height / 2, viewportPadding), maxTop),
            });
        };

        positionTooltip();
        window.addEventListener('resize', positionTooltip);
        return () => window.removeEventListener('resize', positionTooltip);
    }, [tooltipAnchor, tooltipContent]);

    if (!countryAllocation) {
        return (
            <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-slate-900/80 to-slate-950/90 backdrop-blur-xl shadow-2xl shadow-black/40 p-5">
                <p className="text-gray-500 text-sm">No country data available</p>
            </div>
        );
    }

    const visibleCountries = Object.entries(countryAllocation)
        .map(([code, data]) => ({
            code,
            ...data,
            net: data.long - data.short,
            gross: data.long + data.short,
        }))
        .filter(country => country.gross > 0)
        .sort((a, b) => b.gross - a.gross);

    const getCountryColor = (geoName: string) => {
        const isoCode = COUNTRY_NAMES[geoName];
        if (!isoCode || !countryAllocation[isoCode]) return '#182518';
        const data = countryAllocation[isoCode];
        const netExposure = data.long - data.short;
        if (netExposure > 0.15) return '#009900';
        if (netExposure > 0.05) return '#33ff33';
        if (netExposure > 0)    return '#66ff66';
        if (netExposure < -0.1) return '#c25400';
        if (netExposure < 0)    return '#ff770f';
        return '#517051';
    };

    const showTooltip = (geo: { properties: { name: string } }, evt: React.MouseEvent) => {
        const isoCode = COUNTRY_NAMES[geo.properties.name];
        if (isoCode && countryAllocation[isoCode]) {
            setTooltipContent(current => current?.name === geo.properties.name
                ? current
                : { name: geo.properties.name, data: countryAllocation[isoCode] });
            setTooltipAnchor(current => (
                Math.abs(current.x - evt.clientX) < 8 && Math.abs(current.y - evt.clientY) < 8
                    ? current
                    : { x: evt.clientX, y: evt.clientY }
            ));
        }
    };

    const handleMouseLeave = () => {
        setTooltipContent(null);
        setTooltipPos(null);
    };

    const fmtP = (v: number) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`;

    return (
        <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-slate-900/80 to-slate-950/90 backdrop-blur-xl shadow-2xl shadow-black/40 overflow-hidden relative">

            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.06] bg-white/[0.02]">
                <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-white/10">
                        <Globe2 className="h-4 w-4 text-cyan-400" />
                    </div>
                    <div>
                        <h3 className="text-[15px] font-semibold text-white tracking-tight">Geographic Exposure</h3>
                        <p className="text-[11px] text-gray-500 mt-0.5">Net long/short allocation by country</p>
                    </div>
                </div>

                {/* Legend */}
                <div className="hidden sm:flex items-center gap-4 text-[10px] text-gray-500">
                    <span className="flex items-center gap-1.5">
                        <span className="w-3 h-3 rounded-sm bg-emerald-500/70" />
                        Net Long
                    </span>
                    <span className="flex items-center gap-1.5">
                        <span className="w-3 h-3 rounded-sm bg-rose-500/70" />
                        Net Short
                    </span>
                    <span className="flex items-center gap-1.5">
                        <span className="w-3 h-3 rounded-sm bg-slate-700" />
                        No Exposure
                    </span>
                </div>
            </div>

            {/* Map */}
            <div className="h-[380px]">
                <ComposableMap
                    projectionConfig={{ rotate: [-10, 0, 0], scale: 180 }}
                    style={{ width: '100%', height: '100%' }}
                >
                    <ZoomableGroup>
                        <Geographies geography={geoUrl}>
                            {({ geographies }: { geographies: { rsmKey: string; properties: { name: string } }[] }) =>
                                geographies.map((geo) => (
                                    <Geography
                                        key={geo.rsmKey}
                                        geography={geo}
                                        fill={getCountryColor(geo.properties.name)}
                                        stroke="rgba(180,255,180,0.06)"
                                        strokeWidth={0.5}
                                        style={{
                                            default: { outline: 'none', transition: 'fill 0.2s' },
                                            hover: { fill: '#3cdd3c', outline: 'none', cursor: 'pointer' },
                                            pressed: { outline: 'none' },
                                        }}
                                        onMouseEnter={(evt: React.MouseEvent) => showTooltip(geo, evt)}
                                        onMouseMove={(evt: React.MouseEvent) => showTooltip(geo, evt)}
                                        onMouseLeave={handleMouseLeave}
                                    />
                                ))
                            }
                        </Geographies>
                    </ZoomableGroup>
                </ComposableMap>
            </div>

            <div className="grid grid-cols-2 gap-2 border-t border-white/[0.06] bg-white/[0.015] p-3 sm:grid-cols-4 lg:grid-cols-7">
                {visibleCountries.map(country => (
                    <div
                        key={country.code}
                        className="min-w-0 rounded-lg border border-white/[0.07] bg-slate-950/55 px-2.5 py-2"
                    >
                        <div className="mb-1 flex items-center justify-between gap-2">
                            <span className="font-mono text-[11px] font-black tracking-wide text-gray-300">{country.code}</span>
                            <span className={`font-mono text-[10px] font-bold ${country.net >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                                {fmtP(country.net)}
                            </span>
                        </div>
                        <div className="flex items-center gap-1.5 text-[9px] font-mono font-bold">
                            <span className="text-emerald-400">{(country.long * 100).toFixed(1)}L</span>
                            <span className="text-gray-600">/</span>
                            <span className="text-rose-400">{(country.short * 100).toFixed(1)}S</span>
                        </div>
                    </div>
                ))}
            </div>

            {tooltipContent && typeof document !== 'undefined' && createPortal(
                <div
                    ref={tooltipRef}
                    className="pointer-events-none fixed z-[200] w-[min(430px,calc(100vw-24px))] overflow-hidden rounded-lg border border-white/[0.1] bg-slate-950/95 shadow-2xl shadow-black/70 backdrop-blur-xl"
                    style={{
                        left: tooltipPos?.left ?? -10000,
                        top: tooltipPos?.top ?? -10000,
                        visibility: tooltipPos ? 'visible' : 'hidden',
                        maxHeight: 'calc(100vh - 24px)',
                    }}
                >
                    <div className="border-b border-white/[0.07] px-4 py-3">
                        <div className="mb-2 flex items-center justify-between gap-4">
                            <p className="truncate text-[11px] font-bold uppercase tracking-[0.16em] text-cyan-300">
                                {tooltipContent.name}
                            </p>
                            <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.12em] text-gray-500">
                                {tooltipContent.data.tickers.length} positions
                            </span>
                        </div>
                        <div className="grid grid-cols-4 gap-3 font-mono tabular-nums">
                            <div>
                                <p className="mb-0.5 text-[9px] uppercase text-gray-500">Long</p>
                                <p className="text-sm font-black text-emerald-300">{(tooltipContent.data.long * 100).toFixed(1)}%</p>
                            </div>
                            <div>
                                <p className="mb-0.5 text-[9px] uppercase text-gray-500">Short</p>
                                <p className="text-sm font-black text-rose-300">{(tooltipContent.data.short * 100).toFixed(1)}%</p>
                            </div>
                            <div>
                                <p className="mb-0.5 text-[9px] uppercase text-gray-500">Net</p>
                                <p className={`text-sm font-black ${(tooltipContent.data.long - tooltipContent.data.short) >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                                    {fmtP(tooltipContent.data.long - tooltipContent.data.short)}
                                </p>
                            </div>
                            <div className="text-right">
                                <p className="mb-0.5 text-[9px] uppercase text-gray-500">Contrib.</p>
                                <p className={`text-sm font-black ${tooltipContent.data.contribution >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                                    {fmtP(tooltipContent.data.contribution)}
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="px-4 py-3">
                        <div className="mb-2 grid grid-cols-[minmax(0,1fr)_auto_auto] gap-2 border-b border-white/[0.05] pb-1.5 text-[8px] font-bold uppercase tracking-[0.12em] text-gray-600 sm:grid-cols-2">
                            <span>Position</span>
                            <span className="sm:hidden">Weight</span>
                            <span className="text-right sm:hidden">Contribution</span>
                            <span className="hidden sm:block">Position</span>
                        </div>
                        <div className="grid max-h-[min(390px,calc(100vh-150px))] grid-cols-1 gap-x-5 gap-y-1 overflow-y-auto pr-1 sm:grid-cols-2">
                            {tooltipContent.data.tickers.map(t => (
                                <div key={t.ticker} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-b border-white/[0.035] py-1.5 font-mono tabular-nums">
                                    <div className="flex min-w-0 items-center gap-1.5">
                                        <span className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[8px] font-black ${t.type === 'Long' ? 'bg-emerald-500/12 text-emerald-300' : 'bg-rose-500/12 text-rose-300'}`}>
                                            {t.type === 'Long' ? 'L' : 'S'}
                                        </span>
                                        <span className="truncate text-[10px] font-bold text-gray-200">{t.ticker}</span>
                                    </div>
                                    <span className="whitespace-nowrap text-[9px] font-semibold text-gray-400">
                                        {(Math.abs(t.weight) * 100).toFixed(1)}%
                                    </span>
                                    <span className={`min-w-[48px] whitespace-nowrap text-right text-[9px] font-bold ${t.contribution >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                                        {fmtP(t.contribution)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>,
                document.body,
            )}
        </div>
    );
});

CountryMapWidget.displayName = 'CountryMapWidget';
