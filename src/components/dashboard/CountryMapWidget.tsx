import React, { useState, memo } from 'react';
import {
    ComposableMap,
    Geographies,
    Geography,
    ZoomableGroup
} from 'react-simple-maps';

// TopoJSON URL for world map
const geoUrl = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

// Country name to ISO Alpha-3 mapping (for matching with our data)
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

// Reverse mapping for display (kept for potential future use)
// const COUNTRY_DISPLAY: Record<string, string> = { ... };

interface CountryAllocation {
    long: number;
    short: number;
    tickers: { ticker: string; weight: number; type: string }[];
}

interface CountryMapWidgetProps {
    countryAllocation?: Record<string, CountryAllocation>;
}

export const CountryMapWidget: React.FC<CountryMapWidgetProps> = memo(({ countryAllocation }) => {
    const [tooltipContent, setTooltipContent] = useState<{ name: string; data: CountryAllocation } | null>(null);
    const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

    if (!countryAllocation) {
        return (
            <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-lg">
                <h3 className="text-lg font-semibold text-white mb-4">Geographic Allocation</h3>
                <p className="text-muted-foreground">No country data available</p>
            </div>
        );
    }

    const getCountryColor = (geoName: string) => {
        const isoCode = COUNTRY_NAMES[geoName];
        if (!isoCode || !countryAllocation[isoCode]) {
            return '#1e293b'; // Default gray for no exposure
        }

        const data = countryAllocation[isoCode];
        const netExposure = data.long - data.short;

        if (netExposure > 0.1) return '#10b981'; // Strong green (net long)
        if (netExposure > 0) return '#34d399';   // Light green
        if (netExposure < -0.1) return '#ef4444'; // Strong red (net short)
        if (netExposure < 0) return '#f87171';    // Light red
        return '#6b7280'; // Neutral gray (balanced)
    };

    const handleMouseEnter = (geo: { properties: { name: string } }, evt: React.MouseEvent) => {
        const isoCode = COUNTRY_NAMES[geo.properties.name];
        if (isoCode && countryAllocation[isoCode]) {
            setTooltipContent({ name: geo.properties.name, data: countryAllocation[isoCode] });
            setTooltipPos({ x: evt.clientX, y: evt.clientY });
        }
    };

    const handleMouseLeave = () => {
        setTooltipContent(null);
    };

    return (
        <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-lg relative">
            <h3 className="text-lg font-semibold text-white mb-4">Geographic Allocation</h3>

            {/* Legend */}
            <div className="absolute top-4 right-4 flex gap-4 text-xs">
                <div className="flex items-center gap-1">
                    <div className="w-3 h-3 rounded bg-emerald-500"></div>
                    <span className="text-muted-foreground">Net Long</span>
                </div>
                <div className="flex items-center gap-1">
                    <div className="w-3 h-3 rounded bg-rose-500"></div>
                    <span className="text-muted-foreground">Net Short</span>
                </div>
            </div>

            <div className="h-[600px]">
                <ComposableMap
                    projectionConfig={{
                        rotate: [-10, 0, 0],
                        scale: 180
                    }}
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
                                        stroke="#334155"
                                        strokeWidth={0.5}
                                        style={{
                                            default: { outline: 'none' },
                                            hover: {
                                                fill: '#60a5fa',
                                                outline: 'none',
                                                cursor: 'pointer'
                                            },
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

            {/* Tooltip */}
            {tooltipContent && (
                <div
                    className="fixed z-50 bg-slate-900 border border-white/20 rounded-lg p-3 shadow-xl pointer-events-none"
                    style={{
                        left: tooltipPos.x + 10,
                        top: tooltipPos.y - 10,
                        transform: 'translateY(-100%)'
                    }}
                >
                    <p className="font-semibold text-white mb-2">{tooltipContent.name}</p>
                    <div className="flex gap-4 text-sm mb-2">
                        <span className="text-emerald-400">Long: {(tooltipContent.data.long * 100).toFixed(1)}%</span>
                        <span className="text-rose-400">Short: {(tooltipContent.data.short * 100).toFixed(1)}%</span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                        {tooltipContent.data.tickers.map(t => (
                            <span key={t.ticker} className={`mr-2 ${t.type === 'Long' ? 'text-emerald-300' : 'text-rose-300'}`}>
                                {t.ticker}
                            </span>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
});

CountryMapWidget.displayName = 'CountryMapWidget';
