import { useCallback, useEffect, useRef, useState } from 'react';

/** Mirrors backend/health.py. Severity order: ok < unknown < warn < fail. */
export type HealthStatus = 'ok' | 'unknown' | 'warn' | 'fail';

export interface HealthCheck {
    name: string;
    status: HealthStatus;
    summary: string;
    action?: string | null;
    detail?: Record<string, unknown>;
}

export interface HealthReport {
    status: HealthStatus;
    checkedAt: string;
    issueCount: number;
    issues: HealthCheck[];
    checks: HealthCheck[];
    inputErrors?: string[];
}

/** Poll /api/health. A failed poll keeps the last good report and says so, rather
 *  than blanking the indicator: "unreachable" is itself the most important state. */
export function useHealth(url: string, pollMs = 60_000) {
    const [report, setReport] = useState<HealthReport | null>(null);
    const [error, setError] = useState<string | null>(null);
    const inFlight = useRef(false);

    const refresh = useCallback(async (force = false) => {
        if (inFlight.current) return;
        inFlight.current = true;
        try {
            const response = await fetch(force ? `${url}?refresh=true` : url, { cache: 'no-store' });
            if (!response.ok) throw new Error(`health HTTP ${response.status}`);
            setReport(await response.json() as HealthReport);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            inFlight.current = false;
        }
    }, [url]);

    useEffect(() => {
        void refresh();
        const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh(); }, pollMs);
        return () => window.clearInterval(timer);
    }, [refresh, pollMs]);

    return { report, error, refresh };
}
