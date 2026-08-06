import React, { useCallback, useState } from 'react';
import {
    AlertTriangle,
    ChevronDown,
    ChevronRight,
    ExternalLink,
    Gauge,
    LoaderCircle,
    RefreshCw,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { api, brainErrorText } from '../lib/brainApi';

type CoverageFile = {
    driveFileId?: string;
    name?: string;
    relativePath?: string;
    extension?: string | null;
    sizeBytes?: number | null;
    webViewLink?: string;
    status: string;
    reason?: string;
    pages?: number | null;
    pagesRead?: number | null;
    wordsInBrain?: number | null;
    estimatedMissingWords?: number | null;
    estimateBasis?: string;
};

type CoverageReport = {
    folderId?: string | null;
    listingComplete?: boolean;
    coverage?: {
        filesPercent?: number | null;
        filesPartialPercent?: number | null;
        pdfPagesPercent?: number | null;
        tokensPercentEstimate?: number | null;
        embeddedChunksPercent?: number | null;
    };
    counts?: Record<string, number>;
    volume?: {
        indexedWords?: number;
        indexedTokens?: number;
        estimatedMissingTokens?: number;
        estimatedTotalTokens?: number;
        pdfPagesRead?: number;
        pdfPagesTotal?: number;
    };
    notes?: string[];
    files?: CoverageFile[];
};

const STATUS_LABEL: Record<string, string> = {
    indexed_complete: 'Fully indexed',
    indexed_truncated: 'Cut short',
    never_indexed_unsupported: 'No extractor',
    never_indexed_too_large: 'Too large',
    never_indexed_no_text: 'No text layer',
    never_indexed_not_synced: 'Not synced yet',
    excluded_transcript: 'Transcript (excluded)',
};

const STATUS_TONE: Record<string, string> = {
    indexed_complete: 'text-emerald-300',
    indexed_truncated: 'text-amber-300',
    never_indexed_unsupported: 'text-rose-300',
    never_indexed_too_large: 'text-rose-300',
    never_indexed_no_text: 'text-rose-300',
    never_indexed_not_synced: 'text-sky-300',
    excluded_transcript: 'text-slate-500',
};

const PROBLEM_STATUSES = new Set([
    'indexed_truncated',
    'never_indexed_unsupported',
    'never_indexed_too_large',
    'never_indexed_no_text',
    'never_indexed_not_synced',
]);

const formatCount = (value?: number | null) =>
    typeof value === 'number' ? new Intl.NumberFormat('en-US').format(Math.round(value)) : '-';

const formatPercent = (value?: number | null) => (typeof value === 'number' ? `${value}%` : '-');

const percentTone = (value?: number | null) => {
    if (typeof value !== 'number') return 'text-slate-400';
    if (value >= 95) return 'text-emerald-300';
    if (value >= 70) return 'text-amber-300';
    return 'text-rose-300';
};

/** One headline number plus what it is measured against. */
const Metric: React.FC<{ label: string; value?: number | null; detail: string; exact: boolean }> = ({
    label,
    value,
    detail,
    exact,
}) => (
    <div className="rounded-md border border-white/[0.06] bg-black/15 px-3 py-2.5">
        <div className="flex items-baseline justify-between gap-2">
            <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-slate-500">{label}</span>
            <span className={cn('text-[9px] font-bold uppercase tracking-[0.06em]', exact ? 'text-slate-600' : 'text-amber-500/70')}>
                {exact ? 'exact' : 'estimate'}
            </span>
        </div>
        <p className={cn('mt-1 text-xl font-bold tabular-nums', percentTone(value))}>{formatPercent(value)}</p>
        <p className="mt-0.5 text-[10px] leading-4 text-slate-500">{detail}</p>
    </div>
);

export const BrainDriveCoverage: React.FC<{ disabled?: boolean }> = ({ disabled = false }) => {
    const [report, setReport] = useState<CoverageReport | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');
    const [isFilesOpen, setIsFilesOpen] = useState(false);

    const load = useCallback(async () => {
        setIsLoading(true);
        setError('');
        try {
            const response = await fetch(api('/api/brain/drive/coverage'));
            if (!response.ok) throw new Error(await brainErrorText(response, 'Could not measure Drive coverage.'));
            setReport(await response.json() as CoverageReport);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Could not measure Drive coverage.');
        } finally {
            setIsLoading(false);
        }
    }, []);

    const coverage = report?.coverage;
    const counts = report?.counts ?? {};
    const volume = report?.volume;
    const problems = (report?.files ?? []).filter(file => PROBLEM_STATUSES.has(file.status));

    return (
        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-4">
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Gauge className="h-4 w-4 text-sky-300" />
                    <h2 className="text-[11px] font-bold uppercase tracking-[0.11em] text-slate-300">Drive coverage</h2>
                </div>
                <button
                    type="button"
                    onClick={() => void load()}
                    disabled={disabled || isLoading}
                    className="inline-flex min-h-7 items-center gap-1.5 rounded-md border border-sky-500/20 bg-sky-500/[0.07] px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-sky-200 transition-colors hover:bg-sky-500/[0.13] disabled:cursor-not-allowed disabled:border-white/[0.08] disabled:bg-white/[0.025] disabled:text-slate-600"
                >
                    {isLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    {report ? 'Re-measure' : 'Measure'}
                </button>
            </div>

            <p className="mt-2 text-[11px] leading-5 text-slate-500">
                Lists your Drive folder live and compares it against what the Brain actually holds. Indexed and
                fully indexed are different things, and this is where the difference shows up.
            </p>

            {error && (
                <p className="mt-3 flex items-start gap-2 rounded-md border border-rose-400/20 bg-rose-400/[0.05] px-3 py-2 text-xs leading-5 text-rose-200/90">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span className="min-w-0">{error}</span>
                </p>
            )}

            {isLoading && !report && (
                <p className="mt-3 flex items-center gap-2 text-[11px] text-slate-500">
                    <LoaderCircle className="h-3.5 w-3.5 animate-spin text-sky-300" /> Listing Drive and joining it against the index.
                </p>
            )}

            {report && (
                <div className="mt-3 space-y-3 border-t border-white/[0.07] pt-3">
                    <div className="grid grid-cols-2 gap-2">
                        <Metric
                            label="Files complete"
                            value={coverage?.filesPercent}
                            detail={`${formatCount(counts.indexed_complete)} of ${formatCount(counts.countedFiles)} files`}
                            exact
                        />
                        <Metric
                            label="Content in Brain"
                            value={coverage?.tokensPercentEstimate}
                            detail={`~${formatCount(volume?.indexedTokens)} of ~${formatCount(volume?.estimatedTotalTokens)} tokens`}
                            exact={false}
                        />
                        <Metric
                            label="PDF pages read"
                            value={coverage?.pdfPagesPercent}
                            detail={`${formatCount(volume?.pdfPagesRead)} of ${formatCount(volume?.pdfPagesTotal)} pages`}
                            exact
                        />
                        <Metric
                            label="Chunks embedded"
                            value={coverage?.embeddedChunksPercent}
                            detail={`${formatCount(counts.embeddedChunks)} of ${formatCount(counts.chunks)} chunks`}
                            exact
                        />
                    </div>

                    <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 rounded-md border border-white/[0.06] bg-black/15 px-3 py-2.5 text-[10px]">
                        {Object.keys(STATUS_LABEL)
                            .filter(status => (counts[status] ?? 0) > 0)
                            .map(status => (
                                <div key={status} className="flex items-baseline justify-between gap-2">
                                    <dt className="truncate text-slate-500">{STATUS_LABEL[status]}</dt>
                                    <dd className={cn('shrink-0 font-bold tabular-nums', STATUS_TONE[status])}>{counts[status]}</dd>
                                </div>
                            ))}
                    </dl>

                    {!!report.notes?.length && (
                        <ul className="space-y-1">
                            {report.notes.map(note => (
                                <li key={note} className="text-[10px] leading-4 text-slate-500">· {note}</li>
                            ))}
                        </ul>
                    )}

                    {problems.length > 0 && (
                        <div>
                            <button
                                type="button"
                                onClick={() => setIsFilesOpen(open => !open)}
                                className="flex w-full items-center gap-2 text-left"
                            >
                                {isFilesOpen ? <ChevronDown className="h-3.5 w-3.5 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-500" />}
                                <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-slate-400">
                                    {problems.length} file(s) not fully in the Brain
                                </span>
                            </button>
                            {isFilesOpen && (
                                <div className="mt-2 max-h-80 space-y-1.5 overflow-y-auto pr-1">
                                    {problems.slice(0, 100).map(file => (
                                        <article key={file.driveFileId ?? file.name} className="rounded-md border border-white/[0.06] bg-black/15 px-2.5 py-2">
                                            <div className="flex items-start justify-between gap-2">
                                                <p className="min-w-0 truncate text-[11px] font-medium text-slate-200" title={file.relativePath ?? file.name}>
                                                    {file.name}
                                                </p>
                                                {file.webViewLink && (
                                                    <a href={file.webViewLink} target="_blank" rel="noreferrer" className="shrink-0 text-slate-600 hover:text-sky-300">
                                                        <ExternalLink className="h-3 w-3" />
                                                    </a>
                                                )}
                                            </div>
                                            <p className={cn('mt-0.5 text-[10px] font-semibold', STATUS_TONE[file.status])}>
                                                {STATUS_LABEL[file.status] ?? file.status}
                                            </p>
                                            <p className="mt-0.5 text-[10px] leading-4 text-slate-500">{file.reason}</p>
                                            {!!file.estimatedMissingWords && (
                                                <p className="mt-0.5 text-[10px] text-slate-600">
                                                    ~{formatCount(file.estimatedMissingWords)} words missing
                                                    {file.estimateBasis === 'byte_ratio' ? ' (estimated from file size)' : ''}
                                                </p>
                                            )}
                                        </article>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </section>
    );
};
