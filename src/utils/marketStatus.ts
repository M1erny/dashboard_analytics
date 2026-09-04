/** Reading the backend's market-data status: is the dashboard actually behind?
 *
 *  The backend's `stale` flag means exactly one thing: the live fetch failed and
 *  saved frames were served instead. That is NOT the same as the figures being
 *  out of date, and rendering the two as one told an owner his dashboard was
 *  broken while it was showing the most recent close in existence. Markets are
 *  shut most of the time; a snapshot taken at the last close holds precisely what
 *  a successful fetch would have returned.
 *
 *  So the UI asks a different question - how old is the newest market date? -
 *  and only escalates when whole sessions are missing.
 */
import type { MarketDataStatus } from './finance';

/** Calendar days, not trading days, on purpose: a real trading-day count needs a
 *  holiday calendar per venue (Warsaw, Tokyo, Seoul, Toronto and New York are all
 *  in this book), and the only decision resting on this is how loudly to present
 *  the data. Four covers a long weekend, so a Friday close still reads as current
 *  when looked at on Tuesday. */
export const CURRENT_WITHIN_DAYS = 4;

/** Age of a YYYY-MM-DD market date in calendar days, or null if unreadable.
 *  Compared at local midnight so a time of day cannot flip the answer. */
export const marketDateAgeDays = (asOf?: string | null, now: Date = new Date()): number | null => {
    if (!asOf) return null;
    const marketDate = new Date(`${asOf}T00:00:00`);
    if (Number.isNaN(marketDate.getTime())) return null;
    const today = new Date(now);
    today.setHours(0, 0, 0, 0);
    return Math.round((today.getTime() - marketDate.getTime()) / 86_400_000);
};

/** True when the figures are genuinely behind, as opposed to merely unrefreshed.
 *  An unknown or unreadable market date counts as behind: silence about how old
 *  data is should not read as a promise that it is current. */
export const marketDataIsBehind = (status?: MarketDataStatus | null, now: Date = new Date()): boolean => {
    if (status?.stale !== true) return false;
    const age = marketDateAgeDays(status.asOf, now);
    return age === null || age > CURRENT_WITHIN_DAYS;
};
