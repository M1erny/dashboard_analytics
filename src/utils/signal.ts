/** Per-holding signal: what a position HAS done, never what it will do.
 *
 *  Kept out of the component file on purpose. It is pure logic with no JSX, the
 *  audit harness imports it directly, and a component module that also exports
 *  functions breaks fast refresh.
 */

/** Everything below describes what the position HAS done, never what it will do.
 *
 *  Three measured components, each side-adjusted so a short reads correctly - a
 *  falling price is a good outcome for a short, and a signal that ignored that
 *  would rank the book upside down:
 *
 *    trend  agreement of the 1D / 7D / 1M returns, -1 each when they go against
 *           the position, so the range is -3..+3 before weighting
 *    rs     relative strength against the position's own benchmark, already
 *           computed for every holding but until now only shown for the top and
 *           bottom three
 *    volume 7D average volume over YTD average. Not a direction of its own: it
 *           tells you whether the trend is carried on real participation, so it
 *           scales conviction instead of adding to it.
 */
const SIGNAL_VOLUME_STRONG = 1.25;
const SIGNAL_VOLUME_THIN = 0.75;

export type SignalBreakdown = {
    score: number;          // -1..+1, side-adjusted
    trend: number;          // -3..+3
    relativeStrength: number | null;
    volumeRatio: number | null;
    conviction: 'heavy' | 'normal' | 'thin' | null;
    horizons: number;       // how many of the three return horizons were present
};

export function computeSignal(row: {
    r1d: number | null;
    r7d: number | null;
    r1m: number | null;
    direction: 'Long' | 'Short' | null;
    volumeIndicator: number | null;
    status?: 'Active' | 'Exited' | 'Planned';
}, relativeStrength: number | null): SignalBreakdown | null {
    // An exited position has no state to read. Its returns are still carried in
    // the row for contribution accounting, and scoring them produced a confident
    // reading - STLA scored a full -1.00 - about a holding that is gone. The
    // benchmark comparison is already absent for these, so the signal would have
    // rested on half its inputs while rendering identically to a whole one.
    if (row.status && row.status !== 'Active') return null;

    // A short profits when the price falls, so every return flips sign first.
    const side = row.direction === 'Short' ? -1 : 1;
    const horizons = [row.r1d, row.r7d, row.r1m].filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
    if (!horizons.length) return null;

    const trend = horizons.reduce((sum, value) => sum + Math.sign(value * side), 0);
    const rs = typeof relativeStrength === 'number' && Number.isFinite(relativeStrength)
        ? relativeStrength * side
        : null;

    // Normalise trend to -1..+1 over the horizons actually available, so a
    // position missing its 1M history is not silently scored as weaker.
    const trendScore = trend / horizons.length;
    // Relative strength is a return difference; ±10pp is treated as a full
    // reading, beyond which more does not make the signal more true.
    const rsScore = rs === null ? null : Math.max(-1, Math.min(1, rs / 0.10));

    const ratio = typeof row.volumeIndicator === 'number' && Number.isFinite(row.volumeIndicator)
        ? row.volumeIndicator
        : null;
    const conviction = ratio === null ? null
        : ratio >= SIGNAL_VOLUME_STRONG ? 'heavy'
        : ratio <= SIGNAL_VOLUME_THIN ? 'thin'
        : 'normal';

    const parts = rsScore === null ? [trendScore] : [trendScore, rsScore];
    let score = parts.reduce((a, b) => a + b, 0) / parts.length;
    // Volume scales conviction rather than voting: a move on thin participation
    // is the same direction with less behind it.
    if (conviction === 'heavy') score *= 1.15;
    else if (conviction === 'thin') score *= 0.7;

    return {
        score: Math.max(-1, Math.min(1, score)),
        trend,
        relativeStrength: rs,
        volumeRatio: ratio,
        conviction,
        horizons: horizons.length,
    };
}

/** Spelled out on hover, because a bar that cannot explain itself is decoration. */
export function describeSignal(row: { direction: 'Long' | 'Short' | null }, signal: SignalBreakdown): string {
    const side = row.direction === 'Short' ? 'short' : 'long';
    const lines = [
        `Measured, not forecast. Signed for the ${side}.`,
        `Trend: ${signal.trend > 0 ? '+' : ''}${signal.trend} of ${signal.horizons} horizons going with the position`,
    ];
    if (signal.relativeStrength != null) {
        lines.push(`Relative strength: ${signal.relativeStrength > 0 ? '+' : ''}${(signal.relativeStrength * 100).toFixed(1)}pp vs benchmark`);
    }
    if (signal.volumeRatio != null) {
        lines.push(`Volume: ${signal.volumeRatio.toFixed(2)}x the YTD average (${signal.conviction})`);
    }
    return lines.join('\n');
}
