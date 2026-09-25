import React, { useEffect, useRef, useState } from 'react';
import { cn } from '../lib/utils';
import { useHealth, type HealthCheck, type HealthStatus } from '../lib/health';

const DOT: Record<HealthStatus, string> = {
    ok: 'bg-emerald-400',
    unknown: 'bg-slate-400',
    warn: 'bg-amber-400',
    fail: 'bg-rose-400',
};
const TEXT: Record<HealthStatus, string> = {
    ok: 'text-emerald-300/90',
    unknown: 'text-slate-400',
    warn: 'text-amber-300',
    fail: 'text-rose-300',
};

/** One always-visible answer to "is anything wrong?", backed by /api/health.
 *
 *  Collapsed it is a dot and a word, so it fits a status bar. Open, it lists every
 *  check with its sentence and, where the page can do something about it, a button.
 *  `actions` maps a check name to a handler, so the Brain can offer "Embed missing
 *  passages" in place while the dashboard, which has no such control, only shows it.
 */
export const HealthIndicator: React.FC<{
    url: string;
    placement?: 'up' | 'down';
    /** Which edge of the indicator the panel lines up with; pick the one facing inward. */
    align?: 'left' | 'right';
    actions?: Partial<Record<string, () => void>>;
    className?: string;
}> = ({ url, placement = 'down', align = 'right', actions, className }) => {
    const { report, error, refresh } = useHealth(url);
    const [open, setOpen] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const onPointer = (event: PointerEvent) => {
            if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
        };
        const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
        window.addEventListener('pointerdown', onPointer);
        window.addEventListener('keydown', onKey);
        return () => { window.removeEventListener('pointerdown', onPointer); window.removeEventListener('keydown', onKey); };
    }, [open]);

    const status: HealthStatus = error && !report ? 'fail' : report?.status ?? 'unknown';
    const label = error && !report
        ? 'Health unreachable'
        : !report
            ? 'Checking…'
            : report.issueCount === 0
                ? 'All systems OK'
                : `${report.issueCount} issue${report.issueCount === 1 ? '' : 's'}`;
    const checks: HealthCheck[] = report?.checks ?? [];
    const ordered = [...checks].sort((a, b) => rank(b.status) - rank(a.status));

    return (
        <div ref={rootRef} className={cn('relative inline-flex', className)}>
            <button
                type="button"
                onClick={() => { setOpen(value => !value); if (!open) void refresh(); }}
                className={cn('inline-flex items-center gap-1.5 whitespace-nowrap transition-colors hover:text-slate-100', TEXT[status])}
                aria-expanded={open}
                aria-label={`System health: ${label}`}
                title={report?.issues?.map(issue => issue.summary).join('\n') || label}
            >
                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', DOT[status])} />
                <span className="font-semibold">{label}</span>
            </button>
            {open && (
                <div
                    role="dialog"
                    aria-label="System health"
                    className={cn(
                        'absolute z-50 w-[min(92vw,420px)] border border-white/[0.12] bg-[#080d08] p-3 text-left text-[11px] normal-case tracking-normal text-slate-300 shadow-2xl',
                        placement === 'up' ? 'bottom-full mb-2' : 'top-full mt-2',
                        align === 'left' ? 'left-0' : 'right-0',
                    )}
                >
                    <div className="mb-2 flex items-center justify-between gap-2 text-[10px] uppercase tracking-[0.1em] text-slate-500">
                        <span>System health</span>
                        <button type="button" onClick={() => void refresh(true)} className="hover:text-slate-200">Recheck</button>
                    </div>
                    {error && <p className="mb-2 text-rose-300">{report ? `Last check failed (${error}); showing the previous report.` : `Could not reach the backend (${error}).`}</p>}
                    <ul className="space-y-2">
                        {ordered.map(check => {
                            const handler = actions?.[check.name];
                            return (
                                <li key={check.name} className="flex gap-2">
                                    <span className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', DOT[check.status])} />
                                    <div className="min-w-0 flex-1">
                                        <p className={cn('leading-5', check.status === 'ok' ? 'text-slate-400' : 'text-slate-200')}>{check.summary}</p>
                                        {check.action && check.status !== 'ok' && (
                                            handler
                                                ? <button type="button" onClick={() => { handler(); setOpen(false); }} className="mt-1 border border-emerald-500/30 px-2 py-0.5 text-emerald-300 hover:bg-emerald-500/10">{check.action}</button>
                                                : <p className="mt-0.5 text-slate-500">→ {check.action}</p>
                                        )}
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                    {report?.checkedAt && <p className="mt-2 text-[10px] text-slate-600">Checked {new Date(report.checkedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</p>}
                </div>
            )}
        </div>
    );
};

function rank(status: HealthStatus): number {
    return { ok: 0, unknown: 1, warn: 2, fail: 3 }[status] ?? 1;
}
