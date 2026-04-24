import React, { useState, memo } from 'react';
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
    const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

    if (!countryAllocation) {
        return (
            <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-slate-900/80 to-slate-950/90 backdrop-blur-xl shadow-2xl shadow-black/40 p-5">
                <p className="text-gray-500 text-sm">No country data available</p>
            </div>
        );
    }

    const getCountryColor = (geoName: string) => {
        const isoCode = COUNTRY_NAMES[geoName];
        if (!isoCode || !countryAllocation[isoCode]) return '#1e293b';
        const data = countryAllocation[isoCode];
        const netExposure = data.long - data.short;
        if (netExposure > 0.15) return '#059669';
        if (netExposure > 0.05) return '#34d399';
        if (netExposure > 0)    return '#6ee7b7';
        if (netExposure < -0.1) return '#dc2626';
        if (netExposure < 0)    return '#f87171';
        return '#6b7280';
    };

    const handleMouseEnter = (geo: { properties: { name: string } }, evt: React.MouseEvent) => {
        const isoCode = COUNTRY_NAMES[geo.properties.name];
        if (isoCode && countryAllocation[isoCode]) {
            setTooltipContent({ name: geo.properties.name, data: countryAllocation[isoCode] });
            setTooltipPos({ x: evt.clientX, y: evt.clientY });
        }
    };

    const handleMouseLeave = () => setTooltipContent(null);

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
                                        stroke="rgba(255,255,255,0.06)"
                                        strokeWidth={0.5}
                                        style={{
                                            default: { outline: 'none', transition: 'fill 0.2s' },
                                            hover: { fill: '#60a5fa', outline: 'none', cursor: 'pointer' },
                                            pressed: { outline: 'none' },
                                        }}
                                        onMouseEnter={(evt: React.MouseEvent) => handleMouseEnter(geo, evt)}
                                        onMouseLeave={handleMouseLeave}
                                    />
                                ))
                            }
                        </Geographies>
                    </ZoomableGroup>
                </ComposableMap>
            </div>

            {/* Glassmorphism Tooltip */}
            {tooltipContent && (
                <div
                    className="fixed z-50 pointer-events-none"
                    style={{ left: tooltipPos.x + 14, top: tooltipPos.y - 14, transform: 'translateY(-100%)' }}
                >
                    <div
                        className="rounded-2xl border border-white/[0.09] shadow-2xl overflow-hidden"
                        style={{ background: 'rgba(10,15,30,0.96)', backdropFilter: 'blur(20px)', minWidth: '200px' }}
                    >
                        {/* Header */}
                        <div className="px-4 pt-3 pb-2.5 border-b border-white/[0.06]">
                            <p className="text-[10px] text-cyan-400/80 uppercase tracking-[0.18em] font-bold mb-1">{tooltipContent.name}</p>
                            <div className="flex gap-3">
                                <div>
                                    <p className="text-[9px] text-gray-500 mb-0.5">Long</p>
                                    <p className="font-mono text-sm font-black text-emerald-400">{(tooltipContent.data.long * 100).toFixed(1)}%</p>
                                </div>
                                <div>
                                    <p className="text-[9px] text-gray-500 mb-0.5">Short</p>
                                    <p className="font-mono text-sm font-black text-rose-400">{(tooltipContent.data.short * 100).toFixed(1)}%</p>
                                </div>
                                <div className="ml-auto text-right">
                                    <p className="text-[9px] text-gray-500 mb-0.5">Contrib</p>
                                    <p className={`font-mono text-sm font-black ${tooltipContent.data.contribution >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {fmtP(tooltipContent.data.contribution)}
                                    </p>
                                </div>
                            </div>
                        </div>

                        {/* Tickers */}
                        <div className="px-4 py-2.5 space-y-1.5">
                            {tooltipContent.data.tickers.map(t => (
                                <div key={t.ticker} className="flex items-center justify-between gap-3">
                                    <span className={`text-[11px] font-mono font-bold ${t.type === 'Long' ? 'text-emerald-300' : 'text-rose-300'}`}>
                                        {t.ticker}
                                    </span>
                                    <div className="flex-1 h-[2px] bg-white/5 rounded-full overflow-hidden mx-1">
                                        <div
                                            className={`h-full rounded-full ${t.type === 'Long' ? 'bg-emerald-500/50' : 'bg-rose-500/50'}`}
                                            style={{ width: `${Math.min(Math.abs(t.weight) * 400, 100)}%` }}
                                        />
                                    </div>
                                    <span className={`text-[10px] font-mono font-bold shrink-0 ${t.contribution >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {fmtP(t.contribution)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
});

CountryMapWidget.displayName = 'CountryMapWidget';
