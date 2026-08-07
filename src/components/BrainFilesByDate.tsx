import React, { useCallback, useEffect, useState } from 'react';
import {
    AlertTriangle,
    ArrowUpRight,
    CalendarClock,
    LoaderCircle,
    RefreshCw,
    Search,
    Wand2,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { api, brainErrorText } from '../lib/brainApi';

type SourceMetadata = {
    fileName?: string;
    relativePath?: string;
    webViewLink?: string;
    driveFileId?: string;
    extension?: string;
    uploadedAt?: string;
    modifiedAt?: string;
    indexedAt?: string;
    truncated?: boolean;
};

type BrainSource = {
    id?: number;
    title?: string;
    kind?: string;
    metadata?: SourceMetadata;
    createdAt?: string;
};

type SourcesResponse = {
    sources?: BrainSource[];
    dateField?: DateField;
    counts?: { returned?: number; withoutDate?: number };
    note?: string | null;
};

type DateField = 'uploaded' | 'modified' | 'indexed';

const DATE_FIELDS: { value: DateField; label: string; hint: string }[] = [
    { value: 'uploaded', label: 'Uploaded', hint: 'When the file appeared in Drive' },
    { value: 'modified', label: 'Modified', hint: 'When the file last changed' },
    { value: 'indexed', label: 'Indexed', hint: 'When the Brain read it' },
];

const METADATA_KEY: Record<DateField, keyof SourceMetadata> = {
    uploaded: 'uploadedAt',
    modified: 'modifiedAt',
    indexed: 'indexedAt',
};

const sourceName = (source: BrainSource) =>
    source.metadata?.fileName ?? source.title ?? source.metadata?.relativePath ?? 'Untitled source';

const sourceLink = (source: BrainSource) => {
    const metadata = source.metadata ?? {};
    if (metadata.webViewLink) return metadata.webViewLink;
    if (metadata.driveFileId) return `https://drive.google.com/file/d/${metadata.driveFileId}/view`;
    return undefined;
};

/** Render an ISO timestamp as a plain date, or say plainly that there isn't one. */
const formatDate = (value?: string) => {
    if (!value) return 'no date';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
    return parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
};

export const BrainFilesByDate: React.FC<{ disabled?: boolean }> = ({ disabled = false }) => {
    const [dateField, setDateField] = useState<DateField>('uploaded');
    const [after, setAfter] = useState('');
    const [before, setBefore] = useState('');
    const [query, setQuery] = useState('');
    const [sort, setSort] = useState<'newest' | 'oldest'>('newest');
    const [response, setResponse] = useState<SourcesResponse | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [isBackfilling, setIsBackfilling] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');

    const load = useCallback(async () => {
        if (disabled) return;
        setIsLoading(true);
        setError('');
        try {
            const params = new URLSearchParams({ dateField, sort, limit: '200' });
            if (after) params.set('after', after);
            if (before) params.set('before', before);
            if (query.trim()) params.set('q', query.trim());
            const request = await fetch(api(`/api/brain/sources?${params.toString()}`));
            if (!request.ok) throw new Error(await brainErrorText(request, 'Could not list files by date.'));
            setResponse(await request.json() as SourcesResponse);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Could not list files by date.');
        } finally {
            setIsLoading(false);
        }
    }, [disabled, dateField, sort, after, before, query]);

    useEffect(() => {
        void load();
        // Only on mount: afterwards the user drives this with Apply.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const backfill = useCallback(async () => {
        setIsBackfilling(true);
        setError('');
        setNotice('');
        try {
            const request = await fetch(api('/api/brain/drive/backfill-dates'), { method: 'POST' });
            if (!request.ok) throw new Error(await brainErrorText(request, 'Could not backfill upload dates.'));
            const payload = await request.json() as { message?: string };
            setNotice(payload.message ?? 'Upload dates backfilled.');
            await load();
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Could not backfill upload dates.');
        } finally {
            setIsBackfilling(false);
        }
    }, [load]);

    const sources = response?.sources ?? [];
    const withoutDate = response?.counts?.withoutDate ?? 0;
    const activeField = DATE_FIELDS.find(item => item.value === dateField);

    return (
        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-4">
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <CalendarClock className="h-4 w-4 text-amber-300" />
                    <h2 className="text-[11px] font-bold uppercase tracking-[0.11em] text-slate-300">Files by date</h2>
                </div>
                <button
                    type="button"
                    onClick={() => void load()}
                    disabled={disabled || isLoading}
                    className="flex h-7 w-7 items-center justify-center rounded-md border border-white/10 text-slate-400 transition-colors hover:bg-white/[0.07] hover:text-white disabled:cursor-not-allowed disabled:text-slate-600"
                    aria-label="Refresh file list"
                >
                    {isLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                </button>
            </div>

            <div className="mt-3 flex gap-1">
                {DATE_FIELDS.map(field => (
                    <button
                        key={field.value}
                        type="button"
                        title={field.hint}
                        onClick={() => setDateField(field.value)}
                        className={cn(
                            'flex-1 rounded-md border px-2 py-1.5 text-[9px] font-bold uppercase tracking-[0.08em] transition-colors',
                            dateField === field.value
                                ? 'border-amber-500/30 bg-amber-500/[0.1] text-amber-200'
                                : 'border-white/[0.08] bg-white/[0.025] text-slate-400 hover:bg-white/[0.05]',
                        )}
                    >
                        {field.label}
                    </button>
                ))}
            </div>
            <p className="mt-1.5 text-[10px] leading-4 text-slate-600">{activeField?.hint}</p>

            <div className="mt-3 grid grid-cols-2 gap-2">
                <label className="block">
                    <span className="text-[9px] font-bold uppercase tracking-[0.08em] text-slate-500">From</span>
                    <input
                        type="date"
                        value={after}
                        onChange={event => setAfter(event.target.value)}
                        className="mt-1 h-9 w-full rounded-md border border-white/[0.09] bg-white/[0.025] px-2 text-xs text-white outline-none focus:border-amber-500/35"
                    />
                </label>
                <label className="block">
                    <span className="text-[9px] font-bold uppercase tracking-[0.08em] text-slate-500">To</span>
                    <input
                        type="date"
                        value={before}
                        onChange={event => setBefore(event.target.value)}
                        className="mt-1 h-9 w-full rounded-md border border-white/[0.09] bg-white/[0.025] px-2 text-xs text-white outline-none focus:border-amber-500/35"
                    />
                </label>
            </div>

            <div className="mt-2 flex gap-2">
                <input
                    value={query}
                    onChange={event => setQuery(event.target.value)}
                    onKeyDown={event => { if (event.key === 'Enter') void load(); }}
                    placeholder="Filter by name or content"
                    className="h-9 min-w-0 flex-1 rounded-md border border-white/[0.09] bg-white/[0.025] px-3 text-xs text-white outline-none placeholder:text-slate-600 focus:border-amber-500/35"
                />
                <button
                    type="button"
                    onClick={() => setSort(current => (current === 'newest' ? 'oldest' : 'newest'))}
                    title="Toggle sort order"
                    className="inline-flex min-h-9 shrink-0 items-center rounded-md border border-white/10 bg-white/[0.035] px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-slate-300 transition-colors hover:bg-white/[0.07]"
                >
                    {sort === 'newest' ? 'Newest' : 'Oldest'}
                </button>
                <button
                    type="button"
                    onClick={() => void load()}
                    disabled={disabled || isLoading}
                    className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/[0.1] px-3 text-[9px] font-bold uppercase tracking-[0.08em] text-amber-100 transition-colors hover:bg-amber-500/[0.18] disabled:cursor-not-allowed disabled:border-white/[0.08] disabled:bg-white/[0.025] disabled:text-slate-600"
                >
                    <Search className="h-3.5 w-3.5" /> Apply
                </button>
            </div>

            {error && (
                <p className="mt-3 flex items-start gap-2 rounded-md border border-rose-400/20 bg-rose-400/[0.05] px-3 py-2 text-xs leading-5 text-rose-200/90">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span className="min-w-0">{error}</span>
                </p>
            )}
            {notice && <p className="mt-3 rounded-md border border-emerald-400/15 bg-emerald-400/[0.05] px-3 py-2 text-xs leading-5 text-emerald-200/90">{notice}</p>}

            {response?.note && (
                <div className="mt-3 rounded-md border border-amber-400/15 bg-amber-400/[0.04] px-3 py-2">
                    <p className="text-[11px] leading-5 text-amber-200/80">
                        {withoutDate} of these have no upload date. Files indexed before the Brain started
                        recording it need a one-off backfill, which lists Drive without re-downloading anything.
                    </p>
                    <button
                        type="button"
                        onClick={() => void backfill()}
                        disabled={disabled || isBackfilling}
                        className="mt-2 inline-flex min-h-7 items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/[0.1] px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-amber-100 transition-colors hover:bg-amber-500/[0.18] disabled:cursor-not-allowed disabled:text-slate-600"
                    >
                        {isBackfilling ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Wand2 className="h-3 w-3" />}
                        Backfill dates
                    </button>
                </div>
            )}

            <div className="mt-3 border-t border-white/[0.07] pt-3">
                <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-slate-500">
                    {sources.length} file{sources.length === 1 ? '' : 's'}
                    {after || before ? ' in range' : ''}
                </p>
                {sources.length === 0 && !isLoading ? (
                    <p className="mt-2 text-[11px] leading-5 text-slate-500">
                        No files match. Widen the range, or clear it to see everything.
                    </p>
                ) : (
                    <div className="mt-2 max-h-96 space-y-1.5 overflow-y-auto pr-1">
                        {sources.map(source => {
                            const link = sourceLink(source);
                            const stamp = source.metadata?.[METADATA_KEY[dateField]] as string | undefined;
                            return (
                                <article key={source.id ?? sourceName(source)} className="flex items-start justify-between gap-2 rounded-md border border-white/[0.06] bg-black/15 px-2.5 py-2">
                                    <div className="min-w-0">
                                        <p className="truncate text-[11px] font-medium text-slate-200" title={source.metadata?.relativePath ?? sourceName(source)}>
                                            {sourceName(source)}
                                        </p>
                                        <p className={cn('mt-0.5 text-[10px]', stamp ? 'text-slate-500' : 'text-amber-400/70')}>
                                            {formatDate(stamp)}
                                            {source.metadata?.truncated ? ' · cut short' : ''}
                                        </p>
                                    </div>
                                    {link && (
                                        <a href={link} target="_blank" rel="noreferrer" className="mt-0.5 shrink-0 text-slate-600 transition-colors hover:text-amber-300" aria-label={`Open ${sourceName(source)}`}>
                                            <ArrowUpRight className="h-3.5 w-3.5" />
                                        </a>
                                    )}
                                </article>
                            );
                        })}
                    </div>
                )}
            </div>
        </section>
    );
};
