import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    ArrowLeft,
    ArrowUpRight,
    BrainCircuit,
    BriefcaseBusiness,
    BookOpenCheck,
    CalendarClock,
    ChevronDown,
    ChevronRight,
    Cloud,
    Command,
    CornerDownLeft,
    Database,
    ExternalLink,
    FileSearch,
    FolderSync,
    GitBranch,
    History,
    LoaderCircle,
    PanelLeft,
    Plus,
    RefreshCw,
    Search,
    Send,
    Sparkles,
    X,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { API_BASE, api } from '../lib/brainApi';
import { BrainSelfBuild } from './BrainSelfBuild';
import { BrainDriveCoverage } from './BrainDriveCoverage';
import { BrainFilesByDate } from './BrainFilesByDate';

type BrainCounts = {
    sources?: number;
    chunks?: number;
};

type EmbeddingStats = {
    total?: number;
    embedded?: number;
    missing?: number;
    coverage?: number;
};

type BrainLlmStatus = {
    configured: boolean;
    generationModel?: string;
    embeddingModel?: string;
};

type BrainStatus = {
    state?: string;
    storage?: string;
    vectorSearch?: string;
    counts?: BrainCounts;
    embeddings?: EmbeddingStats;
    llm?: BrainLlmStatus;
};

type DriveStatus = {
    configured: boolean;
    folderId?: string | null;
    folderUrl?: string | null;
    authConfigured: boolean;
    connected: boolean;
    connectionState?: 'ready' | 'needs_reconnect' | 'read_only' | 'not_configured';
    connectionMessage?: string;
    requestedScope?: string;
    grantedScope?: string | null;
    // null when Google has not reported the granted scopes yet.
    writeScope?: boolean | null;
};

type SourceReference = {
    id?: number;
    kind?: string;
    sourceType?: string;
    title?: string;
    fileName?: string;
    relativePath?: string;
    webUrl?: string;
    driveFileId?: string;
    driveSearchUrl?: string;
    linkType?: 'drive_file' | 'drive_search' | 'web';
    tags?: string[];
    metadata?: Record<string, unknown>;
};

type SearchResult = {
    entityId: number;
    entityType: string;
    title: string;
    body: string;
    sourceId?: number;
    score?: number;
    ordinal?: number;
    pageStart?: number | null;
    pageEnd?: number | null;
    source?: SourceReference | null;
};

type DeepSource = {
    sourceId?: number;
    source?: SourceReference | null;
    hitOrdinals?: number[];
    chunks?: SearchResult[];
    referenceMode?: 'semantic' | 'anchor';
};

type AnalysisContext = {
    retrieved?: SearchResult[];
    deepSources?: DeepSource[];
    references?: DeepSource[];
    fullDocuments?: FullDocumentContext[];
    portfolio?: BrainPortfolioContext;
};

type PortfolioExposure = {
    long?: number;
    short?: number;
    gross?: number;
    net?: number;
};

type BrainPortfolioContext = {
    portfolio?: string;
    generatedAt?: string;
    dataAsOf?: string | null;
    cacheAgeSeconds?: number | null;
    fresh?: boolean | null;
    marketDataRequested?: boolean;
    marketDataAvailable?: boolean;
    positionCount?: number;
    source?: string;
    exposure?: {
        target?: PortfolioExposure;
        currentDrifted?: PortfolioExposure | null;
    };
    performance?: {
        ytdNet?: number | null;
        benchmarkYtd?: number | null;
        activeReturnYtd?: number | null;
        annualizedJensenAlpha?: number | null;
        compoundedCapmAlphaYtd?: number | null;
        betaYtd?: number | null;
    };
};

type FullDocumentContext = {
    sourceId?: number;
    source?: SourceReference | null;
    chunkCount?: number;
    charsIncluded?: number;
    availableChars?: number;
    contextTruncated?: boolean;
    indexTruncated?: boolean;
};

type EspiEntry = {
    date?: string | null;
    time?: string;
    number?: string;
    source?: string;
    issuer?: string | null;
    subject?: string;
    title?: string;
    nodeId: string;
    url: string;
    matchedTicker?: string;
};

type EspiFinancialItem = {
    item: string;
    current?: number | null;
    previous?: number | null;
    currentSecondary?: number | null;
    previousSecondary?: number | null;
};

type EspiReport = {
    nodeId: string;
    url: string;
    source?: string;
    reportType?: string;
    issuerName?: string;
    issuerSymbol?: string;
    preparedOn?: string;
    sector?: string;
    attachments?: Array<{ url: string; fileName: string; label?: string }>;
    financials?: {
        units?: string;
        currency?: string;
        secondaryCurrency?: string;
        items?: EspiFinancialItem[];
    };
};

type EspiListing = {
    entries?: EspiEntry[];
    byTicker?: Record<string, number>;
    queriedTickers?: string[];
    unresolved?: string[];
    failures?: Record<string, string>;
    truncated?: boolean;
    from?: string;
    to?: string;
    message?: string;
};

type RetrievalDiagnostics = {
    semanticHits?: number;
    keywordHits?: number;
    mergedHits?: number;
    expandedFiles?: number;
    semanticAvailable?: boolean;
    weakSemanticFallback?: number;
    referenceSources?: number;
    referenceSemanticHits?: number;
    fullDocuments?: number;
    fullContextChars?: number;
    portfolioPositions?: number;
    portfolioDataAsOf?: string | null;
    portfolioFresh?: boolean | null;
    marketDataRequested?: boolean;
    marketDataReasons?: string[];
    marketDataAvailable?: boolean;
    marketDataError?: string | null;
    indexGap?: string | null;
};

type ReferenceSetResponse = {
    maxSources?: number;
    sourceIds?: number[];
    sources?: SourceReference[];
};

type FullContextSetResponse = ReferenceSetResponse & {
    maxCharsPerSource?: number;
    totalMaxChars?: number;
};

type SystemPromptResponse = {
    systemPrompt?: string;
    defaultSystemPrompt?: string;
    maxChars?: number;
};

type BrainBootstrapSnapshot = {
    savedAt: number;
    status?: BrainStatus | null;
    drive?: DriveStatus | null;
    references?: ReferenceSetResponse;
    fullContext?: FullContextSetResponse;
    systemPrompt?: SystemPromptResponse;
};

type AnalysisResponse = {
    answer: string;
    model: string;
    embeddingModel: string;
    context?: AnalysisContext;
    retrieval?: RetrievalDiagnostics;
    timings?: { totalMs?: number; generationMs?: number; autosaveMs?: number; semanticError?: string; keywordError?: string };
    autosave?: ConversationAutosave;
};

type ConversationAutosave = {
    status: 'saved' | 'unchanged' | 'failed' | 'skipped' | 'unavailable' | 'disabled';
    threadId?: string;
    exchangeId?: string;
    fileId?: string;
    fileName?: string;
    webViewLink?: string;
    folderId?: string;
    savedAt?: string;
    exchangeCount?: number;
    format?: string;
    reason?: string;
};

type AgentCandidate = {
    title: string;
    url: string;
    source?: string;
    filingDate?: string;
    reportDate?: string;
    periodLabel?: string;
    form?: string;
    baseForm?: string;
    confidence?: number;
    trusted?: boolean;
    matchQuality?: string;
    matchReasons?: string[];
    isExactMatch?: boolean;
    isBestMatch?: boolean;
    isAmendment?: boolean;
};

type AgentSearchResponse = {
    candidates?: AgentCandidate[];
    message?: string;
    resolvedCompany?: { ticker?: string; title?: string } | null;
    intent?: {
        requestedForms?: string[];
        requestedYears?: string[];
        requestedQuarter?: number | null;
        needsResultsDocument?: boolean;
    };
    searched?: {
        filingsReviewed?: number;
        archivesLoaded?: number;
        matchingCandidates?: number;
    };
};

type ChatMessage = {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    context?: AnalysisContext;
    retrieval?: RetrievalDiagnostics;
    timingMs?: number;
    status?: string;
    // A failed exchange stays visible but is never replayed to the model as if the
    // Brain had said it. The backend renders every non-user turn as "Assistant: ...".
    failed?: boolean;
};

type SavedThreadSummary = {
    threadId: string;
    title?: string;
    exchangeCount?: number;
    fileId?: string;
    fileName?: string;
    webViewLink?: string;
    createdAt?: string;
    updatedAt?: string;
    size?: number;
};

type SavedThreadListResponse = {
    folderId?: string;
    threads?: SavedThreadSummary[];
};

type LoadedThreadResponse = SavedThreadSummary & {
    messages?: ChatMessage[];
};

type LibrarySearch = {
    label: string;
    results: SearchResult[];
};

const BRAIN_BOOTSTRAP_CACHE_KEY = `investment-brain-bootstrap:${API_BASE}`;
const BRAIN_BOOTSTRAP_CACHE_MAX_AGE_MS = 15 * 60 * 1000;

const readBrainBootstrapSnapshot = (): BrainBootstrapSnapshot | null => {
    if (typeof window === 'undefined') return null;
    try {
        const value = window.sessionStorage.getItem(BRAIN_BOOTSTRAP_CACHE_KEY);
        if (!value) return null;
        const snapshot = JSON.parse(value) as BrainBootstrapSnapshot;
        return Date.now() - snapshot.savedAt <= BRAIN_BOOTSTRAP_CACHE_MAX_AGE_MS ? snapshot : null;
    } catch {
        return null;
    }
};

const writeBrainBootstrapSnapshot = (snapshot: BrainBootstrapSnapshot) => {
    if (typeof window === 'undefined') return;
    try {
        window.sessionStorage.setItem(BRAIN_BOOTSTRAP_CACHE_KEY, JSON.stringify(snapshot));
    } catch {
        // A full browser storage quota should not block the research workflow.
    }
};

const request = async (url: string, options: RequestInit = {}, timeoutMs = 65000) => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } finally {
        window.clearTimeout(timeout);
    }
};

// Single source of truth for how long an ask may run. Used by both the fetch and the
// waiting indicator so the countdown can never disagree with the real abort deadline.
const askTimeoutMs = (fullDocumentCount: number) => (fullDocumentCount ? 150000 : 90000);

/**
 * `fetch` rejects with a bare `TypeError` — "Failed to fetch" in Chrome, "Load
 * failed" in Safari — for every network-level failure alike: a dropped
 * connection, a server process killed mid-request, a refused preflight, a phone
 * changing network. The message names none of them, so the owner is told only
 * that something went wrong.
 *
 * Probing the backend immediately afterwards separates the two cases that need
 * different fixes: the service is still up and this one request was killed, or
 * the service itself went away. The elapsed time separates them further — a
 * failure at two seconds is not the same event as one at a hundred.
 */
const diagnoseAskFailure = async (error: unknown, elapsedMs: number, fullDocumentCount: number) => {
    const seconds = Math.max(1, Math.round(elapsedMs / 1000));
    const fullDocs = fullDocumentCount
        ? ` ${fullDocumentCount} full document${fullDocumentCount === 1 ? '' : 's'} in context is the most expensive setting there is; try fewer.`
        : '';

    if (error instanceof DOMException && error.name === 'AbortError') {
        return `No answer within ${seconds}s, so the request was given up on. The backend may be waking up.${fullDocs}`;
    }
    if (!(error instanceof TypeError)) {
        return error instanceof Error ? error.message : 'The Brain could not complete this question.';
    }

    let backendAlive = false;
    try {
        backendAlive = (await request(api('/api/brain/status'), {}, 12000)).ok;
    } catch {
        backendAlive = false;
    }

    if (backendAlive) {
        return `The connection dropped after ${seconds}s, but the backend is answering again now — so this one request was killed, not the service. That is usually a question too heavy or too slow for the host to hold open.${fullDocs} The Render logs will say whether it was a restart or an out-of-memory kill.`;
    }
    return `The backend stopped responding after ${seconds}s and is still unreachable. It has restarted, gone to sleep, or the connection was lost. Wait for it to come back, then send the question again.`;
};

const errorText = async (response: Response, fallback: string) => {
    const payload = await response.json().catch(() => null) as { detail?: string | { message?: string; reason?: string } } | null;
    if (typeof payload?.detail === 'string') return payload.detail;
    if (payload?.detail) return [payload.detail.message, payload.detail.reason].filter(Boolean).join(' ') || fallback;
    return fallback;
};

const formatCount = (value?: number) => (value ?? 0).toLocaleString();
const formatPercent = (value?: number) => `${Math.round((value ?? 0) * 100)}%`;
const formatSeconds = (value?: number) => typeof value === 'number' ? `${(value / 1000).toFixed(1)}s` : '';
const excerpt = (value: string, length = 190) => value.replace(/\s+/g, ' ').trim().slice(0, length) + (value.length > length ? '...' : '');
const messageId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const conversationId = () => typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;

const sourceName = (source?: SourceReference | null, fallback = 'Untitled source') =>
    source?.title ?? source?.fileName ?? source?.relativePath ?? fallback;

const sourceLink = (source?: SourceReference | null) => {
    if (!source) return undefined;
    const metadata = source.metadata ?? {};
    const candidates = [
        source.webUrl,
        metadata.webViewLink,
        metadata.driveWebViewLink,
        metadata.sourceUrl,
        metadata.finalUrl,
    ];
    for (const candidate of candidates) {
        if (typeof candidate === 'string' && /^https?:\/\//i.test(candidate.trim())) return candidate.trim();
    }
    if (source.driveFileId) return `https://drive.google.com/file/d/${source.driveFileId}/view`;
    if (typeof source.driveSearchUrl === 'string' && /^https?:\/\//i.test(source.driveSearchUrl.trim())) {
        return source.driveSearchUrl.trim();
    }
    const localSearchTerm = source.sourceType === 'local_file'
        ? source.fileName ?? source.title ?? source.relativePath
        : undefined;
    return localSearchTerm
        ? `https://drive.google.com/drive/u/0/search?q=${encodeURIComponent(localSearchTerm)}`
        : undefined;
};

const sourceLinkLabel = (source?: SourceReference | null) =>
    source?.linkType === 'drive_search' || (
        source?.sourceType === 'local_file' && !source.webUrl && !source.driveFileId
    ) ? 'Find in Drive' : source?.linkType === 'web' ? 'Open source' : 'Open file';

const evidenceFor = (context?: AnalysisContext) => {
    const entries: Array<{ key: string; marker?: string; title: string; detail: string; text?: string; link?: string; linkLabel?: string }> = [];
    const used = new Set<string>();

    for (const [documentIndex, document] of (context?.fullDocuments ?? []).entries()) {
        const source = document.source;
        const key = `${String(source?.id ?? document.sourceId ?? 'full-document')}-full-${documentIndex}`;
        const flags = [
            document.contextTruncated ? 'context cap reached' : '',
            document.indexTruncated ? 'index cap reached' : '',
        ].filter(Boolean).join(' · ');
        entries.push({
            key,
            marker: `F${documentIndex + 1}`,
            title: sourceName(source),
            detail: `${formatCount(document.charsIncluded)} characters from ${formatCount(document.chunkCount)} indexed passages${flags ? ` · ${flags}` : ' · full indexed text'}`,
            link: sourceLink(source),
            linkLabel: sourceLinkLabel(source),
        });
    }

    for (const result of context?.retrieved ?? []) {
        const source = result.source;
        const key = String(source?.id ?? result.sourceId ?? `${result.entityType}-${result.entityId}`);
        if (used.has(key)) continue;
        used.add(key);
        const location = typeof result.pageStart === 'number'
            ? `p. ${result.pageStart}${result.pageEnd && result.pageEnd !== result.pageStart ? `-${result.pageEnd}` : ''}`
            : typeof result.ordinal === 'number' ? `passage ${result.ordinal}` : 'retrieved passage';
        entries.push({
            key,
            title: sourceName(source, result.title),
            detail: location,
            text: result.body,
            link: sourceLink(source),
            linkLabel: sourceLinkLabel(source),
        });
    }

    for (const deep of context?.deepSources ?? []) {
        const source = deep.source;
        const key = String(source?.id ?? deep.sourceId ?? `deep-${entries.length}`);
        if (used.has(key)) continue;
        used.add(key);
        const hits = deep.hitOrdinals?.length ? `read around passages ${deep.hitOrdinals.join(', ')}` : 'expanded source read';
        entries.push({
            key,
            title: sourceName(source),
            detail: hits,
            text: deep.chunks?.[0]?.body,
            link: sourceLink(source),
            linkLabel: sourceLinkLabel(source),
        });
    }

    for (const [referenceIndex, reference] of (context?.references ?? []).entries()) {
        const source = reference.source;
        const key = `${String(source?.id ?? reference.sourceId ?? 'reference')}-reference-${referenceIndex}`;
        const semantic = reference.referenceMode === 'semantic';
        entries.push({
            key,
            marker: `R${referenceIndex + 1}`,
            title: sourceName(source),
            detail: semantic ? 'persistent framework · relevant passage' : 'persistent framework · anchor passage',
            text: reference.chunks?.[0]?.body,
            link: sourceLink(source),
            linkLabel: sourceLinkLabel(source),
        });
    }

    return entries.slice(0, 10);
};

const renderInline = (text: string, key: string): React.ReactNode[] => {
    const parts: React.ReactNode[] = [];
    const pattern = /(\[[^\]]+\]\((https?:\/\/[^)\s]+)\)|`([^`]+)`|\*\*([^*]+)\*\*)/g;
    let cursor = 0;

    for (const match of text.matchAll(pattern)) {
        const index = match.index ?? 0;
        if (index > cursor) parts.push(text.slice(cursor, index));
        const [raw, linkRaw, url, code, bold] = match;
        if (linkRaw && url) {
            parts.push(<a key={`${key}-${index}`} href={url} target="_blank" rel="noreferrer" className="font-semibold text-sky-300 underline underline-offset-4">{linkRaw.slice(1, linkRaw.indexOf(']('))}</a>);
        } else if (code) {
            parts.push(<code key={`${key}-${index}`} className="rounded border border-white/10 bg-white/[0.05] px-1.5 py-0.5 font-mono text-emerald-200">{code}</code>);
        } else if (bold) {
            parts.push(<strong key={`${key}-${index}`} className="font-bold text-white">{bold}</strong>);
        } else {
            parts.push(raw);
        }
        cursor = index + raw.length;
    }
    if (cursor < text.length) parts.push(text.slice(cursor));
    return parts.length ? parts : [text];
};

const MarkdownAnswer: React.FC<{ content: string }> = ({ content }) => {
    const lines = content.replace(/\r\n/g, '\n').split('\n');
    const blocks: React.ReactNode[] = [];
    let index = 0;

    while (index < lines.length) {
        const line = lines[index].trim();
        if (!line) {
            index += 1;
            continue;
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
            blocks.push(<h3 key={`h-${index}`} className="pt-1 text-sm font-bold text-white">{renderInline(heading[2], `h-${index}`)}</h3>);
            index += 1;
            continue;
        }
        const list = line.match(/^[-*]\s+(.+)$/) || line.match(/^\d+[.)]\s+(.+)$/);
        if (list) {
            const items: string[] = [];
            while (index < lines.length) {
                const item = lines[index].trim().match(/^[-*]\s+(.+)$/) || lines[index].trim().match(/^\d+[.)]\s+(.+)$/);
                if (!item) break;
                items.push(item[1]);
                index += 1;
            }
            blocks.push(
                <ul key={`l-${index}`} className="list-disc space-y-1.5 pl-5 text-sm leading-6 text-slate-200 marker:text-emerald-300">
                    {items.map((item, itemIndex) => <li key={`${itemIndex}-${item}`}>{renderInline(item, `l-${index}-${itemIndex}`)}</li>)}
                </ul>
            );
            continue;
        }
        const paragraph: string[] = [line];
        index += 1;
        while (index < lines.length && lines[index].trim() && !/^(#{1,4})\s+|^[-*]\s+|^\d+[.)]\s+/.test(lines[index].trim())) {
            paragraph.push(lines[index].trim());
            index += 1;
        }
        blocks.push(<p key={`p-${index}`} className="text-sm leading-6 text-slate-200">{renderInline(paragraph.join(' '), `p-${index}`)}</p>);
    }

    return <div className="space-y-3">{blocks}</div>;
};

const EvidenceList: React.FC<{ context?: AnalysisContext }> = ({ context }) => {
    const [open, setOpen] = useState(false);
    const evidence = useMemo(() => evidenceFor(context), [context]);
    if (!evidence.length) return null;

    return (
        <div className="mt-4 border-t border-white/[0.07] pt-3">
            <button
                type="button"
                onClick={() => setOpen(value => !value)}
                className="inline-flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.11em] text-slate-400 transition-colors hover:text-white"
            >
                <FileSearch className="h-3.5 w-3.5 text-emerald-300" />
                {evidence.length} source{evidence.length === 1 ? '' : 's'} used
                <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
            </button>
            {open && (
                <div className="mt-3 space-y-2">
                    {evidence.map((source, index) => (
                        <article key={source.key} className={cn('rounded-md border border-white/[0.07] bg-black/20 px-3 py-2.5 transition-colors', source.link && 'hover:border-emerald-400/25 hover:bg-emerald-400/[0.025]')}>
                            <div className="flex items-start gap-2">
                                <span className="mt-0.5 font-mono text-[10px] font-bold text-emerald-300">[{source.marker ?? index + 1}]</span>
                                <div className="min-w-0 flex-1">
                                    <div className="flex items-start justify-between gap-3">
                                        {source.link ? (
                                            <a href={source.link} target="_blank" rel="noreferrer" className="group inline-flex min-w-0 items-start gap-1 text-xs font-semibold leading-5 text-slate-100 transition-colors hover:text-emerald-200" title={`Open ${source.title}`}>
                                                <span>{source.title}</span>
                                                <ArrowUpRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-300/80 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                                            </a>
                                        ) : <p className="text-xs font-semibold leading-5 text-slate-100">{source.title}</p>}
                                        {source.link && (
                                            <a href={source.link} target="_blank" rel="noreferrer" className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-500 transition-colors hover:text-emerald-300" aria-label={`Open ${source.title}`}>
                                                {source.linkLabel ?? 'Open file'}
                                            </a>
                                        )}
                                    </div>
                                    <p className="mt-0.5 text-[10px] font-medium text-slate-500">{source.detail}</p>
                                    {source.text && <p className="mt-1.5 text-xs leading-5 text-slate-400">{excerpt(source.text, 240)}</p>}
                                </div>
                            </div>
                        </article>
                    ))}
                </div>
            )}
        </div>
    );
};

const Button: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: 'primary' | 'quiet' | 'success' }> = ({ className, tone = 'quiet', ...props }) => (
    <button
        {...props}
        className={cn(
            'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors disabled:cursor-not-allowed disabled:border-white/[0.08] disabled:bg-white/[0.025] disabled:text-slate-600 sm:min-h-9',
            tone === 'primary' && 'border-emerald-500/35 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/25',
            tone === 'success' && 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100 hover:bg-cyan-500/20',
            tone === 'quiet' && 'border-white/10 bg-white/[0.035] text-slate-300 hover:bg-white/[0.07]',
            className,
        )}
    />
);

// ─── Shell primitives ────────────────────────────────────────
// The Brain grew a column of stacked cards, one per capability. An editor solves
// the same problem differently: one surface for the work, a rail for what you
// have open, a panel for tools you summon, and a status bar for state. These are
// the pieces that shape.

type IconComponent = React.ComponentType<{ className?: string }>;

type WorkbenchTab = 'library' | 'search' | 'filings' | 'drive' | 'code';

const WORKBENCH_TABS: Array<{ id: WorkbenchTab; label: string; short: string; icon: IconComponent }> = [
    { id: 'library', label: 'Library and index', short: 'Index', icon: Database },
    { id: 'search', label: 'Search sources', short: 'Search', icon: Search },
    { id: 'filings', label: 'Filing finder and imports', short: 'Filings', icon: FileSearch },
    { id: 'drive', label: 'Drive files and coverage', short: 'Drive', icon: CalendarClock },
    { id: 'code', label: 'Self-build proposals', short: 'Code', icon: GitBranch },
];

// Shown in shortcut hints. A Ctrl hint on a Mac is worse than no hint.
const modKeyLabel = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent) ? '⌘' : 'Ctrl+';

const IconButton: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }> = ({ label, active, className, ...props }) => (
    <button
        {...props}
        type="button"
        title={label}
        aria-label={label}
        aria-pressed={active}
        className={cn(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:text-slate-700',
            active ? 'bg-white/[0.08] text-white' : 'text-slate-500 hover:bg-white/[0.05] hover:text-slate-200',
            className,
        )}
    />
);

const CHIP_TONES: Record<'violet' | 'cyan' | 'amber' | 'slate', string> = {
    violet: 'border-violet-500/25 bg-violet-500/[0.09] text-violet-200',
    cyan: 'border-cyan-500/25 bg-cyan-500/[0.09] text-cyan-200',
    amber: 'border-amber-500/25 bg-amber-500/[0.09] text-amber-200',
    slate: 'border-white/[0.12] bg-white/[0.05] text-slate-200',
};

/** A piece of context the next question will carry, editable where it is shown. */
const ContextChip: React.FC<{
    onClick: () => void;
    icon: IconComponent;
    tone: keyof typeof CHIP_TONES;
    children: React.ReactNode;
    active?: boolean;
    disabled?: boolean;
    title?: string;
}> = ({ onClick, icon: Icon, tone, children, active, disabled, title }) => (
    <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        title={title}
        className={cn(
            'inline-flex min-h-7 items-center gap-1.5 rounded-md border px-2 text-[10px] font-semibold transition-colors disabled:cursor-not-allowed disabled:border-transparent disabled:bg-transparent disabled:text-slate-700',
            active ? CHIP_TONES[tone] : 'border-transparent text-slate-500 hover:bg-white/[0.05] hover:text-slate-300',
        )}
    >
        <Icon className="h-3.5 w-3.5" />
        {children}
    </button>
);

const PanelSection: React.FC<{ icon: IconComponent; tone: string; title: string; action?: React.ReactNode; children: React.ReactNode }> = ({ icon: Icon, tone, title, action, children }) => (
    <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
                <Icon className={cn('h-4 w-4 shrink-0', tone)} />
                <h2 className="truncate text-[11px] font-bold uppercase tracking-[0.11em] text-slate-300">{title}</h2>
            </div>
            {action}
        </div>
        {children}
    </section>
);

/**
 * What an answer could not use, in the order the owner would act on it. An answer
 * built without the market snapshot, or with nothing retrieved because the index
 * is not embedded, reads exactly like an answer built on everything — unless the
 * gap is stated above it. More than one can be true at once, so they are listed
 * rather than chosen between.
 */
const answerCaveats = (retrieval?: RetrievalDiagnostics, semanticError?: string) => {
    const caveats: string[] = [];
    if (retrieval?.marketDataError) {
        caveats.push(`Live market data was needed for this question but the fetch failed (${retrieval.marketDataError}), so prices, drifted weights, momentum and realised performance are missing from this answer.`);
    }
    if (retrieval?.indexGap) {
        caveats.push(`Nothing was retrieved, and ${retrieval.indexGap}. That is a gap in the index, not proof the library has nothing on the subject.`);
    }
    if (semanticError) {
        caveats.push('Vector retrieval was unavailable; exact search still contributed.');
    }
    if (retrieval?.weakSemanticFallback) {
        caveats.push(`Nothing in the brain cleared the relevance floor. This answer leans on ${retrieval.weakSemanticFallback} weak match${retrieval.weakSemanticFallback === 1 ? '' : 'es'} — read it as an evidence gap, not a finding.`);
    }
    return caveats.length ? caveats.join(' ') : undefined;
};

/** One line describing where an answer's evidence came from. */
const retrievalSummary = (retrieval?: RetrievalDiagnostics) => {
    if (!retrieval) return '';
    const parts = [
        retrieval.semanticAvailable ? `${retrieval.semanticHits ?? 0} semantic` : 'exact search',
        `${retrieval.keywordHits ?? 0} exact`,
    ];
    if (retrieval.referenceSources) parts.push(`${retrieval.referenceSources} framework${retrieval.referenceSources === 1 ? '' : 's'}`);
    if (retrieval.fullDocuments) parts.push(`${retrieval.fullDocuments} full file${retrieval.fullDocuments === 1 ? '' : 's'}`);
    if (retrieval.portfolioPositions) parts.push(`${retrieval.portfolioPositions} ${retrieval.marketDataAvailable ? 'live positions' : 'portfolio targets'}`);
    if (retrieval.expandedFiles) parts.push(`${retrieval.expandedFiles} file read${retrieval.expandedFiles === 1 ? '' : 's'}`);
    return parts.join(' · ');
};

type PaletteCommand = {
    id: string;
    label: string;
    group: string;
    icon: IconComponent;
    hint?: string;
    disabled?: boolean;
    run: () => void;
};

export const InvestmentBrainChat: React.FC = () => {
    const bootstrapSnapshot = useRef<BrainBootstrapSnapshot | null>(readBrainBootstrapSnapshot());
    const [backendState, setBackendState] = useState<'checking' | 'ready' | 'offline'>('checking');
    const [status, setStatus] = useState<BrainStatus | null>(() => bootstrapSnapshot.current?.status ?? null);
    const [drive, setDrive] = useState<DriveStatus | null>(() => bootstrapSnapshot.current?.drive ?? null);
    const [referenceSources, setReferenceSources] = useState<SourceReference[]>(() => bootstrapSnapshot.current?.references?.sources ?? []);
    const [referenceSelection, setReferenceSelection] = useState<number[]>(() => bootstrapSnapshot.current?.references?.sourceIds ?? []);
    const [referenceLimit, setReferenceLimit] = useState(() => bootstrapSnapshot.current?.references?.maxSources ?? 6);
    const [availableReferenceSources, setAvailableReferenceSources] = useState<SourceReference[]>([]);
    const [referenceFilter, setReferenceFilter] = useState('');
    const [isReferencePickerOpen, setIsReferencePickerOpen] = useState(false);
    const [isReferenceLoading, setIsReferenceLoading] = useState(false);
    const [isReferenceSaving, setIsReferenceSaving] = useState(false);
    const [fullContextSources, setFullContextSources] = useState<SourceReference[]>(() => bootstrapSnapshot.current?.fullContext?.sources ?? []);
    const [fullContextSelection, setFullContextSelection] = useState<number[]>(() => bootstrapSnapshot.current?.fullContext?.sourceIds ?? []);
    const [fullContextLimit, setFullContextLimit] = useState(() => bootstrapSnapshot.current?.fullContext?.maxSources ?? 4);
    const [fullContextMaxChars, setFullContextMaxChars] = useState(() => bootstrapSnapshot.current?.fullContext?.maxCharsPerSource ?? 250000);
    const [fullContextTotalMaxChars, setFullContextTotalMaxChars] = useState(() => bootstrapSnapshot.current?.fullContext?.totalMaxChars ?? 800000);
    const [availableFullContextSources, setAvailableFullContextSources] = useState<SourceReference[]>([]);
    const [fullContextFilter, setFullContextFilter] = useState('');
    const [isFullContextPickerOpen, setIsFullContextPickerOpen] = useState(false);
    const [isFullContextLoading, setIsFullContextLoading] = useState(false);
    const [isFullContextSaving, setIsFullContextSaving] = useState(false);
    const [systemPrompt, setSystemPrompt] = useState(() => bootstrapSnapshot.current?.systemPrompt?.systemPrompt ?? '');
    const [savedSystemPrompt, setSavedSystemPrompt] = useState(() => bootstrapSnapshot.current?.systemPrompt?.systemPrompt ?? '');
    const [defaultSystemPrompt, setDefaultSystemPrompt] = useState(() => bootstrapSnapshot.current?.systemPrompt?.defaultSystemPrompt ?? '');
    const [systemPromptLimit, setSystemPromptLimit] = useState(() => bootstrapSnapshot.current?.systemPrompt?.maxChars ?? 6000);
    const [isSystemPromptOpen, setIsSystemPromptOpen] = useState(false);
    const [isSystemPromptLoading, setIsSystemPromptLoading] = useState(false);
    const [isSystemPromptSaving, setIsSystemPromptSaving] = useState(false);
    const [draft, setDraft] = useState('');
    const [thread, setThread] = useState<ChatMessage[]>([]);
    const [threadId, setThreadId] = useState(() => conversationId());
    const [conversationAutosave, setConversationAutosave] = useState<ConversationAutosave | null>(null);
    const [savedThreads, setSavedThreads] = useState<SavedThreadSummary[]>([]);
    const [savedThreadsLoaded, setSavedThreadsLoaded] = useState(false);
    const [isSavedThreadsLoading, setIsSavedThreadsLoading] = useState(false);
    const [portfolioContext, setPortfolioContext] = useState<BrainPortfolioContext | null>(null);
    const [isAsking, setIsAsking] = useState(false);
    const [askElapsed, setAskElapsed] = useState(0);
    const [notice, setNotice] = useState('');
    const [libraryQuery, setLibraryQuery] = useState('');
    const [librarySearch, setLibrarySearch] = useState<LibrarySearch | null>(null);
    const [isSearching, setIsSearching] = useState(false);
    const [agentTask, setAgentTask] = useState('');
    const [agentUrl, setAgentUrl] = useState('');
    const [agentCandidates, setAgentCandidates] = useState<AgentCandidate[]>([]);
    const [filingSource, setFilingSource] = useState<'sec' | 'espi'>('sec');
    const [espiQuery, setEspiQuery] = useState('');
    const [espiDays, setEspiDays] = useState(7);
    const [espiListing, setEspiListing] = useState<EspiListing | null>(null);
    const [isEspiLoading, setIsEspiLoading] = useState(false);
    const [espiOpenNode, setEspiOpenNode] = useState<string | null>(null);
    const [espiReports, setEspiReports] = useState<Record<string, EspiReport>>({});
    const [agentSearch, setAgentSearch] = useState<AgentSearchResponse | null>(null);
    const [isAgentWorking, setIsAgentWorking] = useState(false);
    const outputRef = useRef<HTMLDivElement | null>(null);
    const composerRef = useRef<HTMLDivElement | null>(null);
    const draftRef = useRef<HTMLTextAreaElement | null>(null);

    const refresh = async () => {
        try {
            const [statusResult, driveResult, referenceResult, fullContextResult, systemPromptResult] = await Promise.allSettled([
                request(api('/api/brain/status'), {}, 50000),
                request(api('/api/brain/index/drive/status'), {}, 12000),
                request(api('/api/brain/references'), {}, 12000),
                request(api('/api/brain/full-context'), {}, 12000),
                request(api('/api/brain/system-prompt'), {}, 12000),
            ]);
            if (statusResult.status !== 'fulfilled') throw new Error('Brain backend is unavailable');
            const statusResponse = statusResult.value;
            if (!statusResponse.ok) throw new Error('Brain backend is unavailable');
            const nextStatus = await statusResponse.json() as BrainStatus;
            const nextDrive = driveResult.status === 'fulfilled' && driveResult.value.ok
                ? await driveResult.value.json() as DriveStatus
                : null;
            let nextReferences = bootstrapSnapshot.current?.references;
            let nextFullContext = bootstrapSnapshot.current?.fullContext;
            let nextSystemPrompt = bootstrapSnapshot.current?.systemPrompt;
            setStatus(nextStatus);
            setDrive(nextDrive);
            if (referenceResult.status === 'fulfilled' && referenceResult.value.ok) {
                const references = await referenceResult.value.json() as ReferenceSetResponse;
                nextReferences = references;
                setReferenceSources(references.sources ?? []);
                setReferenceSelection(references.sourceIds ?? []);
                setReferenceLimit(references.maxSources ?? 6);
            }
            if (fullContextResult.status === 'fulfilled' && fullContextResult.value.ok) {
                const fullContext = await fullContextResult.value.json() as FullContextSetResponse;
                nextFullContext = fullContext;
                setFullContextSources(fullContext.sources ?? []);
                setFullContextSelection(fullContext.sourceIds ?? []);
                setFullContextLimit(fullContext.maxSources ?? 4);
                setFullContextMaxChars(fullContext.maxCharsPerSource ?? 250000);
                setFullContextTotalMaxChars(fullContext.totalMaxChars ?? 800000);
            }
            if (systemPromptResult.status === 'fulfilled' && systemPromptResult.value.ok) {
                const prompt = await systemPromptResult.value.json() as SystemPromptResponse;
                nextSystemPrompt = prompt;
                setSystemPrompt(prompt.systemPrompt ?? '');
                setSavedSystemPrompt(prompt.systemPrompt ?? '');
                setDefaultSystemPrompt(prompt.defaultSystemPrompt ?? '');
                setSystemPromptLimit(prompt.maxChars ?? 6000);
            }
            const snapshot = {
                savedAt: Date.now(),
                status: nextStatus,
                drive: nextDrive,
                references: nextReferences,
                fullContext: nextFullContext,
                systemPrompt: nextSystemPrompt,
            } satisfies BrainBootstrapSnapshot;
            bootstrapSnapshot.current = snapshot;
            writeBrainBootstrapSnapshot(snapshot);
            setBackendState('ready');
            void request(api('/api/brain/portfolio-outline'), {}, 12000)
                .then(async response => {
                    if (response.ok) setPortfolioContext(await response.json() as BrainPortfolioContext);
                })
                .catch(() => undefined);
        } catch {
            setBackendState('offline');
        }
    };

    useEffect(() => { void refresh(); }, []);

    useEffect(() => {
        if (!thread.length && !isAsking) return;
        const pane = outputRef.current;
        if (pane) pane.scrollTo({ top: pane.scrollHeight, behavior: 'smooth' });
    }, [thread.length, isAsking]);

    // A question can legitimately run for a minute. Without a clock the owner cannot
    // tell a slow answer from a hung one.
    useEffect(() => {
        if (!isAsking) return;
        const startedAt = Date.now();
        const interval = window.setInterval(() => setAskElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000);
        return () => { window.clearInterval(interval); setAskElapsed(0); };
    }, [isAsking]);

    const ready = backendState === 'ready';
    const counts = status?.counts ?? {};
    const embeddings = status?.embeddings ?? {};
    const allEmbedded = (embeddings.missing ?? 0) === 0 && (embeddings.total ?? counts.chunks ?? 0) > 0;
    const libraryState = !ready ? 'Offline' : !drive?.connected ? 'Drive needs access' : !allEmbedded ? 'Embedding pending' : 'Library ready';
    const displayedExposure = portfolioContext?.marketDataAvailable
        ? portfolioContext.exposure?.currentDrifted
        : portfolioContext?.exposure?.target;
    const portfolioModeLabel = portfolioContext?.marketDataAvailable ? 'Live portfolio' : 'Target portfolio';

    const filteredReferenceSources = useMemo(() => {
        const query = referenceFilter.trim().toLowerCase();
        if (!query) return availableReferenceSources;
        return availableReferenceSources.filter(source => [
            source.title,
            source.fileName,
            source.relativePath,
            source.tags?.join(' '),
        ].filter(Boolean).join(' ').toLowerCase().includes(query));
    }, [availableReferenceSources, referenceFilter]);
    const filteredFullContextSources = useMemo(() => {
        const query = fullContextFilter.trim().toLowerCase();
        if (!query) return availableFullContextSources;
        return availableFullContextSources.filter(source => [
            source.title,
            source.fileName,
            source.relativePath,
            source.tags?.join(' '),
        ].filter(Boolean).join(' ').toLowerCase().includes(query));
    }, [availableFullContextSources, fullContextFilter]);

    const sendQuestion = async () => {
        const question = draft.trim();
        if (!ready || !question || isAsking) return;

        const userMessage: ChatMessage = { id: messageId(), role: 'user', content: question };
        const exchangeId = conversationId();
        const priorConversation = thread
            .filter(message => !message.failed)
            .map(message => ({ role: message.role, content: message.content }));
        setThread(current => [...current, userMessage]);
        setDraft('');
        setIsAsking(true);
        setNotice(fullContextSources.length
            ? `Reading ${fullContextSources.length} full document${fullContextSources.length === 1 ? '' : 's'}, then retrieving supporting evidence...`
            : 'Searching evidence, then reading the strongest source files...');

        const askStartedAt = Date.now();
        try {
            const response = await request(api('/api/brain/analyze-company'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    question,
                    limit: 6,
                    useSemantic: true,
                    conversation: priorConversation.slice(-100),
                    threadId,
                    exchangeId,
                    threadTitle: priorConversation.find(message => message.role === 'user')?.content ?? question,
                    autoSave: true,
                }),
            }, askTimeoutMs(fullContextSources.length));
            if (!response.ok) throw new Error(await errorText(response, 'The Brain could not complete this question.'));
            const payload = await response.json() as AnalysisResponse;
            if (payload.context?.portfolio) setPortfolioContext(payload.context.portfolio);
            if (payload.autosave) setConversationAutosave(payload.autosave);
            setThread(current => [...current, {
                id: messageId(),
                role: 'assistant',
                content: payload.answer,
                context: payload.context,
                retrieval: payload.retrieval,
                timingMs: payload.timings?.totalMs,
                status: answerCaveats(payload.retrieval, payload.timings?.semanticError),
            }]);
            const readCount = payload.retrieval?.expandedFiles ?? 0;
            const fullDocumentCount = payload.retrieval?.fullDocuments ?? 0;
            const liveBook = payload.retrieval?.portfolioPositions
                ? payload.retrieval.marketDataAvailable
                    ? ` with the ${payload.retrieval.portfolioPositions}-position live book as of ${payload.retrieval.portfolioDataAsOf ?? 'the latest market close'}`
                    : payload.retrieval.marketDataError
                        ? ` with the ${payload.retrieval.portfolioPositions}-position target book; the market refresh FAILED`
                        : ` with the ${payload.retrieval.portfolioPositions}-position target book; no market refresh was needed`
                : '';
            const saveNote = payload.autosave?.status === 'saved' || payload.autosave?.status === 'unchanged'
                ? ' Saved to Drive.'
                : payload.autosave?.status === 'failed' || payload.autosave?.status === 'unavailable'
                    ? ' Answer completed, but Drive autosave needs attention.'
                    : '';
            const answeredBy = payload.model ? `${payload.model} answered` : 'Answered';
            const answeredIn = payload.timings?.totalMs ? ` in ${formatSeconds(payload.timings.totalMs)}` : '';
            setNotice(`${answeredBy}${answeredIn}${liveBook}${fullDocumentCount ? ` and ${fullDocumentCount} full document${fullDocumentCount === 1 ? '' : 's'} in context` : readCount ? ` after reading ${readCount} source file${readCount === 1 ? '' : 's'}` : ''}.${saveNote}`);
        } catch (error) {
            const elapsedMs = Date.now() - askStartedAt;
            if (error instanceof TypeError) setNotice('Connection lost. Checking whether the backend is still up...');
            const text = await diagnoseAskFailure(error, elapsedMs, fullContextSources.length);
            setThread(current => [...current, { id: messageId(), role: 'assistant', content: text, status: 'No new conclusion was generated.', failed: true }]);
            // Give the question back so it can be retried without retyping. Only when the
            // composer is still empty: the textarea stays editable during the wait.
            setDraft(current => current.trim() ? current : question);
            setNotice(text);
        } finally {
            setIsAsking(false);
        }
    };

    const searchLibrary = async () => {
        const query = libraryQuery.trim();
        if (!ready || !query || isSearching) return;
        setIsSearching(true);
        setLibrarySearch(null);
        try {
            const semantic = await request(api(`/api/brain/search/semantic?${new URLSearchParams({ q: query, limit: '8' })}`), {}, 18000);
            if (semantic.ok) {
                const payload = await semantic.json() as { results?: SearchResult[] };
                const results = payload.results ?? [];
                if (results.length) {
                    setLibrarySearch({ label: 'Semantic matches', results });
                    return;
                }
            }
            const keyword = await request(api(`/api/brain/search?${new URLSearchParams({ q: query, limit: '8' })}`), {}, 12000);
            if (!keyword.ok) throw new Error(await errorText(keyword, 'Search is unavailable.'));
            const payload = await keyword.json() as { results?: SearchResult[] };
            setLibrarySearch({ label: 'Exact matches', results: payload.results ?? [] });
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Search is unavailable.');
        } finally {
            setIsSearching(false);
        }
    };

    const connectDrive = async () => {
        try {
            const response = await request(api('/api/brain/drive/auth-url'), {}, 12000);
            if (!response.ok) throw new Error(await errorText(response, 'Google Drive connection is not configured.'));
            const payload = await response.json() as { url?: string };
            if (!payload.url) throw new Error('Google Drive authorization URL is missing.');
            window.open(payload.url, '_blank', 'noopener,noreferrer');
            setNotice('Google Drive authorization opened in a new tab. Return here once it is approved.');
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Google Drive connection could not start.');
        }
    };

    const syncDrive = async () => {
        setNotice('Starting Drive sync...');
        try {
            const response = await request(api('/api/brain/index/drive/start'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // Send no limits of our own. The backend owns the ceilings, and a
                // payload that undercuts them strands files without saying so.
                body: JSON.stringify({ force: false }),
            }, 12000);
            if (!response.ok) throw new Error(await errorText(response, 'Drive sync could not start.'));
            setNotice('Drive sync started in the background. New or changed files will be indexed.');
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Drive sync could not start.');
        }
    };

    const embedMissing = async () => {
        setNotice('Starting embedding backfill...');
        try {
            const response = await request(api('/api/brain/embeddings/backfill/start'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // The backend owns the throughput ceilings. A payload that
                // undercuts them turns one Embed click into many.
                body: JSON.stringify({ force: false }),
            }, 12000);
            if (!response.ok) throw new Error(await errorText(response, 'Embedding job could not start.'));
            setNotice('Embedding is running in the background. Search remains available while it finishes.');
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Embedding job could not start.');
        }
    };

    const openReferencePicker = async () => {
        if (!ready) return;
        setIsReferencePickerOpen(true);
        setReferenceFilter('');
        setIsReferenceLoading(true);
        try {
            const response = await request(api('/api/brain/sources?limit=250'), {}, 16000);
            if (!response.ok) throw new Error(await errorText(response, 'Could not load your research files.'));
            const payload = await response.json() as { sources?: SourceReference[] };
            setAvailableReferenceSources(payload.sources ?? []);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Could not load your research files.');
        } finally {
            setIsReferenceLoading(false);
        }
    };

    const closeReferencePicker = useCallback(() => {
        setReferenceSelection(referenceSources.flatMap(source => typeof source.id === 'number' ? [source.id] : []));
        setIsReferencePickerOpen(false);
    }, [referenceSources]);

    const toggleReferenceSource = (sourceId: number) => {
        setReferenceSelection(current => {
            if (current.includes(sourceId)) return current.filter(id => id !== sourceId);
            if (current.length >= referenceLimit) {
                setNotice(`Choose up to ${referenceLimit} persistent reference sources.`);
                return current;
            }
            return [...current, sourceId];
        });
    };

    const saveReferenceSet = async (sourceIds = referenceSelection, closeAfterSave = false) => {
        if (!ready || isReferenceSaving) return;
        setIsReferenceSaving(true);
        try {
            const response = await request(api('/api/brain/references'), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sourceIds }),
            }, 18000);
            if (!response.ok) throw new Error(await errorText(response, 'Could not save the reference layer.'));
            const payload = await response.json() as ReferenceSetResponse;
            setReferenceSources(payload.sources ?? []);
            setReferenceSelection(payload.sourceIds ?? []);
            setReferenceLimit(payload.maxSources ?? 6);
            setNotice(payload.sources?.length
                ? `${payload.sources.length} reference source${payload.sources.length === 1 ? '' : 's'} will shape every future answer.`
                : 'The persistent reference layer is now empty.');
            if (closeAfterSave) setIsReferencePickerOpen(false);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Could not save the reference layer.');
        } finally {
            setIsReferenceSaving(false);
        }
    };

    const openFullContextPicker = async () => {
        if (!ready) return;
        setIsFullContextPickerOpen(true);
        setFullContextFilter('');
        setIsFullContextLoading(true);
        try {
            const response = await request(api('/api/brain/sources?limit=250'), {}, 16000);
            if (!response.ok) throw new Error(await errorText(response, 'Could not load your indexed research files.'));
            const payload = await response.json() as { sources?: SourceReference[] };
            setAvailableFullContextSources(payload.sources ?? []);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Could not load your indexed research files.');
        } finally {
            setIsFullContextLoading(false);
        }
    };

    const closeFullContextPicker = useCallback(() => {
        setFullContextSelection(fullContextSources.flatMap(source => typeof source.id === 'number' ? [source.id] : []));
        setIsFullContextPickerOpen(false);
    }, [fullContextSources]);

    // Escape closes the two source pickers. Deliberately not bound for the system-prompt
    // editor: closing it reverts to the saved prompt, so a stray key would discard edits.
    useEffect(() => {
        if (!isReferencePickerOpen && !isFullContextPickerOpen) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            if (isReferencePickerOpen) closeReferencePicker();
            else closeFullContextPicker();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [isReferencePickerOpen, isFullContextPickerOpen, closeReferencePicker, closeFullContextPicker]);

    const toggleFullContextSource = (sourceId: number) => {
        setFullContextSelection(current => {
            if (current.includes(sourceId)) return current.filter(id => id !== sourceId);
            if (current.length >= fullContextLimit) {
                setNotice(`Choose up to ${fullContextLimit} full-document sources.`);
                return current;
            }
            return [...current, sourceId];
        });
    };

    const saveFullContextSet = async (sourceIds = fullContextSelection, closeAfterSave = false) => {
        if (!ready || isFullContextSaving) return;
        setIsFullContextSaving(true);
        try {
            const response = await request(api('/api/brain/full-context'), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sourceIds }),
            }, 18000);
            if (!response.ok) {
                throw new Error(response.status === 404
                    ? 'The full-document context service will be available after the backend deploys.'
                    : await errorText(response, 'Could not save the full-document context.'));
            }
            const payload = await response.json() as FullContextSetResponse;
            setFullContextSources(payload.sources ?? []);
            setFullContextSelection(payload.sourceIds ?? []);
            setFullContextLimit(payload.maxSources ?? 4);
            setFullContextMaxChars(payload.maxCharsPerSource ?? fullContextMaxChars);
            setFullContextTotalMaxChars(payload.totalMaxChars ?? fullContextTotalMaxChars);
            setNotice(payload.sources?.length
                ? `${payload.sources.length} full document${payload.sources.length === 1 ? '' : 's'} will be in every future answer.`
                : 'The full-document context layer is now empty.');
            if (closeAfterSave) setIsFullContextPickerOpen(false);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Could not save the full-document context.');
        } finally {
            setIsFullContextSaving(false);
        }
    };

    const openSystemPrompt = async () => {
        if (!ready) return;
        setIsSystemPromptOpen(true);
        setIsSystemPromptLoading(true);
        try {
            const response = await request(api('/api/brain/system-prompt'), {}, 12000);
            if (!response.ok) {
                throw new Error(response.status === 404
                    ? 'The AI system-prompt service will be available after the backend deploys.'
                    : await errorText(response, 'Could not load the AI system prompt.'));
            }
            const payload = await response.json() as SystemPromptResponse;
            const prompt = payload.systemPrompt ?? '';
            setSystemPrompt(prompt);
            setSavedSystemPrompt(prompt);
            setDefaultSystemPrompt(payload.defaultSystemPrompt ?? '');
            setSystemPromptLimit(payload.maxChars ?? 6000);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Could not load the AI system prompt.');
        } finally {
            setIsSystemPromptLoading(false);
        }
    };

    const closeSystemPrompt = () => {
        setSystemPrompt(savedSystemPrompt);
        setIsSystemPromptOpen(false);
    };

    const saveSystemPrompt = async () => {
        if (!ready || isSystemPromptSaving) return;
        setIsSystemPromptSaving(true);
        try {
            const response = await request(api('/api/brain/system-prompt'), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ systemPrompt }),
            }, 18000);
            if (!response.ok) {
                throw new Error(response.status === 404
                    ? 'The AI system-prompt service will be available after the backend deploys.'
                    : await errorText(response, 'Could not save the AI system prompt.'));
            }
            const payload = await response.json() as SystemPromptResponse;
            const savedPrompt = payload.systemPrompt ?? '';
            setSystemPrompt(savedPrompt);
            setSavedSystemPrompt(savedPrompt);
            setDefaultSystemPrompt(payload.defaultSystemPrompt ?? defaultSystemPrompt);
            setSystemPromptLimit(payload.maxChars ?? systemPromptLimit);
            setIsSystemPromptOpen(false);
            setNotice('AI system prompt saved. It will guide every future answer.');
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Could not save the AI system prompt.');
        } finally {
            setIsSystemPromptSaving(false);
        }
    };

    const findOfficialSources = async () => {
        if (!ready || !agentTask.trim() || isAgentWorking) return;
        setIsAgentWorking(true);
        setAgentCandidates([]);
        setAgentSearch(null);
        setNotice('Searching SEC filings by form and reporting period...');
        try {
            const response = await request(api('/api/brain/agent/find-official-sources'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task: agentTask.trim(), limit: 10 }),
            }, 45000);
            if (!response.ok) throw new Error(await errorText(response, 'Official source search failed.'));
            const payload = await response.json() as AgentSearchResponse;
            setAgentCandidates(payload.candidates ?? []);
            setAgentSearch(payload);
            setNotice(payload.message ?? (payload.candidates?.length ? `${payload.candidates.length} official filings found.` : 'No matching official filing found.'));
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Official source search failed.');
        } finally {
            setIsAgentWorking(false);
        }
    };

    const importUrl = async (url: string, title?: string, trustedOnly = false) => {
        if (!ready || !url || isAgentWorking) return;
        setIsAgentWorking(true);
        setNotice('Importing, indexing, and queuing embeddings...');
        try {
            const response = await request(api('/api/brain/agent/import-url'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url,
                    title,
                    tags: ['research-agent'],
                    trustedOnly,
                    uploadToDrive: true,
                    keepOriginal: true,
                    embedAfterImport: true,
                    embedMaxChunks: 500,
                    agentTask: agentTask.trim() || undefined,
                }),
            }, 90000);
            if (!response.ok) throw new Error(await errorText(response, 'Source import failed.'));
            const payload = await response.json() as {
                status?: string;
                chunks?: unknown[];
                driveFile?: { webViewLink?: string };
                document?: {
                    convertedToMarkdown?: boolean;
                    original?: { keptOnDrive?: boolean; extension?: string; uploadError?: string | null };
                };
            };
            setAgentUrl('');
            const original = payload.document?.original;
            // Name the format rather than saying "original", so it is obvious the
            // readable file is there and not only the flattened Markdown.
            const originalNote = original?.keptOnDrive
                ? ` The ${(original.extension ?? '').replace('.', '').toUpperCase() || 'original'} was saved next to it.`
                : original?.uploadError
                    ? ' The Markdown is indexed, but saving the original file failed.'
                    : '';
            setNotice(payload.status === 'skipped'
                ? 'That source was already indexed and has not changed.'
                : `Source indexed as ${payload.chunks?.length ?? 0} passages${payload.document?.convertedToMarkdown ? ' in Markdown' : ''}${payload.driveFile?.webViewLink ? ' and saved to Drive' : ''}.${originalNote}`);
            await refresh();
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Source import failed.');
        } finally {
            setIsAgentWorking(false);
        }
    };

    const runAndImport = async () => {
        if (!ready || !agentTask.trim() || isAgentWorking) return;
        setIsAgentWorking(true);
        setNotice('Finding and importing the best official source...');
        try {
            const response = await request(api('/api/brain/agent/run'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    task: agentTask.trim(),
                    importBest: true,
                    uploadToDrive: true,
                    embedAfterImport: true,
                    embedMaxChunks: 500,
                }),
            }, 90000);
            if (!response.ok) throw new Error(await errorText(response, 'Research agent could not complete the import.'));
            const payload = await response.json() as { plan?: AgentSearchResponse; import?: { status?: string; chunks?: unknown[] } };
            setAgentCandidates(payload.plan?.candidates ?? []);
            setAgentSearch(payload.plan ?? null);
            setNotice(payload.import?.status === 'skipped'
                ? 'The strongest official source was already indexed.'
                : `Official source imported as ${payload.import?.chunks?.length ?? 0} passages.`);
            await refresh();
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Research agent could not complete the import.');
        } finally {
            setIsAgentWorking(false);
        }
    };

    const loadEspiDigest = async (days = espiDays) => {
        if (!ready || isEspiLoading) return;
        setIsEspiLoading(true);
        setNotice(`Checking what your Polish holdings filed in the last ${days} day${days === 1 ? '' : 's'}...`);
        try {
            const response = await request(api(`/api/brain/espi/digest?days=${days}`), {}, 120000);
            if (!response.ok) throw new Error(await errorText(response, 'The ESPI/EBI digest could not be loaded.'));
            const payload = await response.json() as EspiListing;
            setEspiListing(payload);
            const count = payload.entries?.length ?? 0;
            setNotice(payload.message
                ?? `${count} filing${count === 1 ? '' : 's'} from your Polish holdings${payload.truncated ? ' (more may exist beyond the page limit)' : ''}.`);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'The ESPI/EBI digest could not be loaded.');
        } finally {
            setIsEspiLoading(false);
        }
    };

    const searchEspi = async () => {
        const query = espiQuery.trim();
        if (!ready || !query || isEspiLoading) return;
        setIsEspiLoading(true);
        setNotice(`Searching ESPI/EBI for "${query}"...`);
        try {
            const response = await request(api(`/api/brain/espi/search?q=${encodeURIComponent(query)}`), {}, 90000);
            if (!response.ok) throw new Error(await errorText(response, 'The ESPI/EBI search failed.'));
            const payload = await response.json() as EspiListing;
            setEspiListing(payload);
            const count = payload.entries?.length ?? 0;
            setNotice(`${count} ESPI/EBI filing${count === 1 ? '' : 's'} for "${query}"${payload.truncated ? ' (more may exist beyond the page limit)' : ''}.`);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'The ESPI/EBI search failed.');
        } finally {
            setIsEspiLoading(false);
        }
    };

    const toggleEspiReport = async (nodeId: string) => {
        if (espiOpenNode === nodeId) { setEspiOpenNode(null); return; }
        setEspiOpenNode(nodeId);
        if (espiReports[nodeId]) return;
        try {
            const response = await request(api(`/api/brain/espi/report/${encodeURIComponent(nodeId)}`), {}, 60000);
            if (!response.ok) throw new Error(await errorText(response, 'This report could not be read.'));
            const payload = await response.json() as EspiReport;
            setEspiReports(current => ({ ...current, [nodeId]: payload }));
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'This report could not be read.');
            setEspiOpenNode(null);
        }
    };

    const loadSavedThreads = async () => {
        if (!ready || isSavedThreadsLoading) return;
        setIsSavedThreadsLoading(true);
        try {
            const response = await request(api('/api/brain/conversations?limit=30'), {}, 50000);
            if (!response.ok) throw new Error(await errorText(response, 'Saved Brain threads could not be loaded.'));
            const payload = await response.json() as SavedThreadListResponse;
            setSavedThreads(payload.threads ?? []);
            setSavedThreadsLoaded(true);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'Saved Brain threads could not be loaded.');
        } finally {
            setIsSavedThreadsLoading(false);
        }
    };

    const resumeSavedThread = async (savedThread: SavedThreadSummary) => {
        if (!ready || isAsking || isSavedThreadsLoading) return;
        setIsSavedThreadsLoading(true);
        try {
            const response = await request(api(`/api/brain/conversations/${encodeURIComponent(savedThread.threadId)}`), {}, 50000);
            if (!response.ok) throw new Error(await errorText(response, 'This Brain thread could not be resumed.'));
            const payload = await response.json() as LoadedThreadResponse;
            const messages = (payload.messages ?? []).map(message => ({ ...message, id: message.id || messageId() }));
            setThreadId(payload.threadId ?? savedThread.threadId);
            setThread(messages);
            setConversationAutosave({
                status: 'saved',
                threadId: payload.threadId ?? savedThread.threadId,
                fileId: payload.fileId ?? savedThread.fileId,
                fileName: payload.fileName ?? savedThread.fileName,
                webViewLink: payload.webViewLink ?? savedThread.webViewLink,
                exchangeCount: payload.exchangeCount ?? savedThread.exchangeCount,
                format: 'markdown+yaml+json',
            });
            const latestPortfolio = [...messages].reverse().find(message => message.context?.portfolio)?.context?.portfolio;
            if (latestPortfolio) setPortfolioContext(latestPortfolio);
            setNotice(`Resumed ${payload.exchangeCount ?? savedThread.exchangeCount ?? 0} saved exchange${(payload.exchangeCount ?? savedThread.exchangeCount) === 1 ? '' : 's'} from Drive. New questions will retrieve current source evidence again.`);
        } catch (error) {
            setNotice(error instanceof Error ? error.message : 'This Brain thread could not be resumed.');
        } finally {
            setIsSavedThreadsLoading(false);
        }
    };

    const resetThread = () => {
        setThread([]);
        setThreadId(conversationId());
        setConversationAutosave(null);
        setDraft('');
        setNotice('New research thread.');
        draftRef.current?.focus();
    };

    // ─── Shell state ─────────────────────────────────────────
    const [isRailOpen, setIsRailOpen] = useState(() => typeof window === 'undefined' || window.innerWidth >= 1024);
    const [panelTab, setPanelTab] = useState<WorkbenchTab | null>(null);
    const [isPaletteOpen, setIsPaletteOpen] = useState(false);
    const [paletteQuery, setPaletteQuery] = useState('');

    const togglePanel = (tab: WorkbenchTab) => setPanelTab(current => (current === tab ? null : tab));

    // The rail needs a name for the open thread before the transcript has one.
    const firstQuestion = thread.find(message => message.role === 'user')?.content.trim();
    const threadTitle = firstQuestion ? excerpt(firstQuestion, 64) : 'New thread';

    // The thread list is navigation, so it loads with the page rather than on a click.
    useEffect(() => {
        if (!ready || savedThreadsLoaded || isSavedThreadsLoading) return;
        void loadSavedThreads();
        // loadSavedThreads is recreated every render; the guards above are what stop a loop.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ready, savedThreadsLoaded]);

    const paletteCommands = useMemo<PaletteCommand[]>(() => {
        const commands: PaletteCommand[] = [
            { id: 'new-thread', label: 'New thread', group: 'Thread', icon: Plus, disabled: isAsking, run: resetThread },
            { id: 'reload-threads', label: 'Reload saved threads', group: 'Thread', icon: History, disabled: !ready || isSavedThreadsLoading, run: () => void loadSavedThreads() },
            { id: 'reference', label: 'Reference layer', group: 'Context', icon: BookOpenCheck, disabled: !ready, hint: referenceSources.length ? referenceSources.map(source => sourceName(source)).join(' · ') : 'No standing framework selected', run: () => void openReferencePicker() },
            { id: 'full-files', label: 'Full-document context', group: 'Context', icon: FileSearch, disabled: !ready, hint: fullContextSources.length ? fullContextSources.map(source => sourceName(source)).join(' · ') : 'No whole files selected', run: () => void openFullContextPicker() },
            { id: 'prompt', label: 'AI system prompt', group: 'Context', icon: Sparkles, disabled: !ready, hint: systemPrompt ? excerpt(systemPrompt, 72) : 'Default research instructions', run: () => void openSystemPrompt() },
            { id: 'search', label: 'Search sources', group: 'Library', icon: Search, run: () => setPanelTab('search') },
            { id: 'filings', label: 'Find an SEC filing', group: 'Library', icon: FileSearch, run: () => setPanelTab('filings') },
            { id: 'index', label: 'Library and index status', group: 'Library', icon: Database, run: () => setPanelTab('library') },
            { id: 'embed', label: `Embed missing passages${embeddings.missing ? ` (${formatCount(embeddings.missing)})` : ''}`, group: 'Library', icon: Sparkles, disabled: !ready || (embeddings.missing ?? 0) === 0, run: () => void embedMissing() },
            { id: 'files-by-date', label: 'Drive files by upload date', group: 'Drive', icon: CalendarClock, run: () => setPanelTab('drive') },
            { id: 'sync', label: drive?.connected ? 'Sync Drive' : 'Connect Google Drive', group: 'Drive', icon: drive?.connected ? FolderSync : Cloud, disabled: !ready, run: () => void (drive?.connected ? syncDrive() : connectDrive()) },
            { id: 'self-build', label: 'Self-build proposals', group: 'Code', icon: GitBranch, run: () => setPanelTab('code') },
            { id: 'refresh', label: 'Refresh Brain status', group: 'View', icon: RefreshCw, run: () => void refresh() },
            { id: 'rail', label: isRailOpen ? 'Hide the thread rail' : 'Show the thread rail', group: 'View', icon: PanelLeft, run: () => setIsRailOpen(open => !open) },
            { id: 'dashboard', label: 'Back to the dashboard', group: 'Go', icon: ArrowLeft, run: () => { window.location.href = '/'; } },
        ];
        if (drive?.folderUrl) {
            commands.push({ id: 'drive-folder', label: 'Open the Drive folder', group: 'Drive', icon: ExternalLink, run: () => window.open(drive.folderUrl!, '_blank', 'noreferrer') });
        }
        return commands;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ready, isAsking, isSavedThreadsLoading, referenceSources, fullContextSources, systemPrompt, embeddings.missing, drive?.connected, drive?.folderUrl, isRailOpen]);

    const paletteMatches = useMemo(() => {
        const query = paletteQuery.trim().toLowerCase();
        if (!query) return paletteCommands;
        return paletteCommands.filter(command => `${command.label} ${command.group} ${command.hint ?? ''}`.toLowerCase().includes(query));
    }, [paletteCommands, paletteQuery]);

    // Editor-style shortcuts. Escape closes the palette; the source pickers keep
    // their own Escape handler because closing those discards a selection.
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            const mod = event.metaKey || event.ctrlKey;
            if (mod && event.key.toLowerCase() === 'k') {
                event.preventDefault();
                setPaletteQuery('');
                setIsPaletteOpen(open => !open);
                return;
            }
            if (mod && event.key.toLowerCase() === 'b') {
                event.preventDefault();
                setIsRailOpen(open => !open);
                return;
            }
            if (mod && event.key.toLowerCase() === 'n' && !isAsking) {
                event.preventDefault();
                resetThread();
                return;
            }
            if (event.key === 'Escape' && isPaletteOpen) setIsPaletteOpen(false);
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [isPaletteOpen, isAsking]);

    return (
        <div className="flex h-[100dvh] flex-col overflow-hidden bg-[#06080d] text-foreground">
            <div className="h-px shrink-0 bg-gradient-to-r from-emerald-400 via-cyan-400 to-violet-400" />

            <div className="flex min-h-0 flex-1">
                {/* ── Rail: threads, the way an editor lists the work that is open ── */}
                {isRailOpen && (
                    <>
                        <div className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden" onClick={() => setIsRailOpen(false)} aria-hidden="true" />
                        <nav aria-label="Research threads" className="fixed inset-y-0 left-0 z-40 flex w-[268px] shrink-0 flex-col border-r border-white/[0.07] bg-[#080c14] lg:static lg:z-auto">
                            <div className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-white/[0.07] pl-3 pr-2">
                                <a href="/" className="inline-flex min-w-0 items-center gap-2 text-slate-300 transition-colors hover:text-white" title="Back to the dashboard">
                                    <BrainCircuit className="h-4 w-4 shrink-0 text-emerald-300" />
                                    <span className="truncate text-xs font-bold tracking-tight">Investment Brain</span>
                                </a>
                                <IconButton onClick={() => setIsRailOpen(false)} label="Hide the thread rail"><PanelLeft className="h-4 w-4" /></IconButton>
                            </div>

                            <div className="p-2">
                                <button
                                    type="button"
                                    onClick={resetThread}
                                    disabled={isAsking}
                                    className="flex w-full items-center gap-2 rounded-md border border-white/[0.09] bg-white/[0.03] px-2.5 py-2 text-xs font-semibold text-slate-200 transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/[0.07] hover:text-white disabled:cursor-not-allowed disabled:text-slate-600"
                                >
                                    <Plus className="h-3.5 w-3.5 text-emerald-300" /> New thread
                                    <kbd className="ml-auto font-mono text-[9px] text-slate-600">{modKeyLabel}N</kbd>
                                </button>
                            </div>

                            <div className="flex items-center justify-between gap-2 px-3 pb-1 pt-1">
                                <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-600">Threads</span>
                                <IconButton onClick={() => void loadSavedThreads()} disabled={!ready || isSavedThreadsLoading} label="Refresh saved threads">
                                    {isSavedThreadsLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                                </IconButton>
                            </div>

                            <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
                                {thread.length > 0 && (
                                    <button type="button" className="w-full rounded-md border border-emerald-500/25 bg-emerald-500/[0.07] px-2.5 py-2 text-left">
                                        <p className="truncate text-xs font-semibold text-white">{threadTitle}</p>
                                        <p className="mt-0.5 text-[10px] text-emerald-300/70">Current · {Math.ceil(thread.length / 2)} exchange{Math.ceil(thread.length / 2) === 1 ? '' : 's'}</p>
                                    </button>
                                )}
                                {savedThreads.filter(saved => saved.threadId !== threadId).map(saved => (
                                    <div key={saved.threadId} className="group flex items-center gap-1 rounded-md px-1 transition-colors hover:bg-white/[0.04]">
                                        <button
                                            type="button"
                                            onClick={() => void resumeSavedThread(saved)}
                                            disabled={isAsking || isSavedThreadsLoading}
                                            className="min-w-0 flex-1 py-2 pl-1.5 text-left disabled:cursor-not-allowed"
                                        >
                                            <p className="truncate text-xs text-slate-300 group-hover:text-white">{saved.title ?? saved.fileName ?? 'Saved thread'}</p>
                                            <p className="mt-0.5 text-[10px] text-slate-600">{saved.exchangeCount ?? 0} exchange{saved.exchangeCount === 1 ? '' : 's'}{saved.updatedAt ? ` · ${new Date(saved.updatedAt).toLocaleDateString()}` : ''}</p>
                                        </button>
                                        {saved.webViewLink && (
                                            <a href={saved.webViewLink} target="_blank" rel="noreferrer" className="shrink-0 p-1.5 text-slate-700 opacity-0 transition-opacity hover:text-emerald-300 group-hover:opacity-100" aria-label="Open this thread in Drive"><ExternalLink className="h-3.5 w-3.5" /></a>
                                        )}
                                    </div>
                                ))}
                                {savedThreadsLoaded && !savedThreads.length && !thread.length && (
                                    <p className="px-2 py-3 text-[11px] leading-5 text-slate-600">No saved threads yet. The first answer creates one in Drive.</p>
                                )}
                                {!savedThreadsLoaded && (
                                    <p className="px-2 py-3 text-[11px] leading-5 text-slate-600">{ready ? 'Loading threads from Drive…' : 'Threads load once the backend is reachable.'}</p>
                                )}
                            </div>

                            <div className="shrink-0 border-t border-white/[0.07] p-2">
                                <button
                                    type="button"
                                    onClick={() => { setPaletteQuery(''); setIsPaletteOpen(true); }}
                                    className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-xs text-slate-500 transition-colors hover:bg-white/[0.04] hover:text-slate-200"
                                >
                                    <Command className="h-3.5 w-3.5" /> Commands
                                    <kbd className="ml-auto font-mono text-[9px] text-slate-600">{modKeyLabel}K</kbd>
                                </button>
                                <a href="/" className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-xs text-slate-500 transition-colors hover:bg-white/[0.04] hover:text-slate-200">
                                    <ArrowLeft className="h-3.5 w-3.5" /> Dashboard
                                </a>
                            </div>
                        </nav>
                    </>
                )}

                {/* ── Editor: the chat is the whole surface ── */}
                <div className="flex min-w-0 flex-1 flex-col">
                    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-white/[0.07] px-2 sm:px-3">
                        {!isRailOpen && <IconButton onClick={() => setIsRailOpen(true)} label="Show the thread rail"><PanelLeft className="h-4 w-4" /></IconButton>}
                        <div className="min-w-0 flex-1 px-1">
                            <p className="truncate text-xs font-semibold text-slate-200">{threadTitle}</p>
                        </div>
                        {conversationAutosave?.webViewLink && (
                            <a href={conversationAutosave.webViewLink} target="_blank" rel="noreferrer" title={conversationAutosave.fileName ?? 'Open the saved transcript in Drive'} className="hidden items-center gap-1.5 rounded-md px-2 py-1.5 text-[10px] font-semibold text-cyan-300/80 transition-colors hover:bg-white/[0.05] hover:text-cyan-200 sm:inline-flex">
                                <Cloud className="h-3.5 w-3.5" /> Saved
                            </a>
                        )}
                        <div className="flex items-center gap-0.5">
                            {WORKBENCH_TABS.map(tab => (
                                <IconButton
                                    key={tab.id}
                                    onClick={() => togglePanel(tab.id)}
                                    active={panelTab === tab.id}
                                    label={tab.label}
                                >
                                    <tab.icon className="h-4 w-4" />
                                </IconButton>
                            ))}
                        </div>
                        <span className="mx-1 hidden h-5 w-px bg-white/[0.08] sm:block" />
                        <IconButton onClick={resetThread} disabled={isAsking} label="New thread"><Plus className="h-4 w-4" /></IconButton>
                    </header>

                    <div ref={outputRef} className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-6 sm:px-6">
                        {!thread.length && !isAsking && (
                            <div className="mx-auto flex h-full max-w-2xl flex-col justify-end pb-2 pt-8">
                                <span className="inline-flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-300"><Sparkles className="h-3.5 w-3.5" /> Evidence-first research</span>
                                <h2 className="mt-3 text-2xl font-bold leading-tight text-white">A second mind for the work that compounds.</h2>
                                <p className="mt-2 max-w-xl text-sm leading-6 text-slate-400">Your portfolio, market momentum, and Drive research retrieved by meaning. Every answer keeps its market date and sources attached.</p>
                                <div className="mt-5 grid gap-1.5 sm:grid-cols-2">
                                    {[
                                        'Where is momentum strongest and weakest in my current book?',
                                        'Which holdings create the most concentration risk today?',
                                        'Where does value accrue in AI infrastructure?',
                                        'What is the strongest bear case?',
                                    ].map(suggestion => (
                                        <button key={suggestion} type="button" onClick={() => setDraft(suggestion)} className="group flex min-h-11 items-start gap-2 rounded-lg border border-white/[0.07] px-3 py-2.5 text-left text-xs leading-5 text-slate-400 transition-colors hover:border-emerald-500/25 hover:bg-emerald-500/[0.05] hover:text-white">
                                            <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-700 transition-colors group-hover:text-emerald-300" />
                                            {suggestion}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="space-y-7">
                            {thread.map(message => (
                                <article key={message.id} className="mx-auto w-full max-w-3xl">
                                    {message.role === 'user' ? (
                                        <div className="flex justify-end">
                                            <p className="max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-sm border border-sky-500/20 bg-sky-500/[0.08] px-4 py-2.5 text-sm leading-6 text-slate-100">{message.content}</p>
                                        </div>
                                    ) : (
                                        <div className="border-l-2 border-emerald-400/25 pl-4 sm:pl-5">
                                            {/* Caveats change how the answer should be read, so they go above it. */}
                                            {message.status && (
                                                <p className="mb-3 rounded-md border border-amber-400/20 bg-amber-400/[0.05] px-3 py-2 text-xs leading-5 text-amber-200/80">{message.status}</p>
                                            )}
                                            <MarkdownAnswer content={message.content} />
                                            <EvidenceList context={message.context} />
                                            {(message.retrieval || message.timingMs) && (
                                                <p className="mt-2.5 text-[10px] leading-4 text-slate-600">
                                                    {[retrievalSummary(message.retrieval), message.timingMs ? formatSeconds(message.timingMs) : null].filter(Boolean).join(' · ')}
                                                </p>
                                            )}
                                        </div>
                                    )}
                                </article>
                            ))}

                            {isAsking && (
                                <article className="mx-auto w-full max-w-3xl border-l-2 border-emerald-400/25 pl-4 sm:pl-5">
                                    <div className="flex items-center gap-2 text-sm text-slate-400">
                                        <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-emerald-300" />
                                        <span>Retrieving the portfolio, market, and research data this question needs.</span>
                                        <span className="ml-auto shrink-0 tabular-nums text-xs text-slate-500">{askElapsed}s</span>
                                    </div>
                                    {askElapsed >= 60 && (
                                        <p className="mt-2 text-xs leading-5 text-amber-200/70">
                                            Still working. This request stops at {Math.round(askTimeoutMs(fullContextSources.length) / 1000)}s, and your question is kept so you can retry.
                                        </p>
                                    )}
                                </article>
                            )}
                        </div>
                    </div>

                    {/* ── Composer: context is attached here, not in a distant panel ── */}
                    <div ref={composerRef} className="shrink-0 px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-6">
                        <div className="mx-auto w-full max-w-3xl rounded-xl border border-white/[0.1] bg-white/[0.025] focus-within:border-emerald-500/35">
                            <div className="flex flex-wrap items-center gap-1 border-b border-white/[0.06] px-2 py-1.5">
                                <ContextChip onClick={() => void openReferencePicker()} disabled={!ready} active={referenceSources.length > 0} tone="violet" icon={BookOpenCheck} title={referenceSources.map(source => sourceName(source)).join('\n') || 'Files used as a standing framework in every answer'}>
                                    Reference{referenceSources.length ? ` ${referenceSources.length}` : ''}
                                </ContextChip>
                                <ContextChip onClick={() => void openFullContextPicker()} disabled={!ready} active={fullContextSources.length > 0} tone="cyan" icon={FileSearch} title={fullContextSources.map(source => sourceName(source)).join('\n') || 'Indexed files included in full, not by retrieval'}>
                                    Full files{fullContextSources.length ? ` ${fullContextSources.length}` : ''}
                                </ContextChip>
                                <ContextChip onClick={() => void openSystemPrompt()} disabled={!ready} active={Boolean(systemPrompt)} tone="amber" icon={Sparkles} title={systemPrompt ? excerpt(systemPrompt, 240) : 'Default research instructions'}>
                                    Prompt
                                </ContextChip>
                                <ContextChip onClick={() => { setPaletteQuery(''); setIsPaletteOpen(true); }} tone="slate" icon={Command} title={`All Brain commands (${modKeyLabel}K)`}>
                                    Tools
                                </ContextChip>
                            </div>
                            <div className="flex items-end gap-2 p-2">
                                <textarea
                                    ref={draftRef}
                                    value={draft}
                                    onChange={event => setDraft(event.target.value)}
                                    onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendQuestion(); } }}
                                    rows={2}
                                    aria-label="Research question"
                                    placeholder="Ask about a company, thesis, trend, or source…"
                                    className="max-h-48 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-6 text-white outline-none placeholder:text-slate-600"
                                />
                                <Button type="button" tone="primary" onClick={() => void sendQuestion()} disabled={!ready || !draft.trim() || isAsking} className="h-9 min-h-9 w-9 shrink-0 px-0" aria-label="Send question">
                                    {isAsking ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                                </Button>
                            </div>
                        </div>
                        <p className="mx-auto mt-1.5 w-full max-w-3xl px-1 text-[10px] text-slate-600">
                            <CornerDownLeft className="mr-1 inline h-3 w-3 align-[-2px]" />send · Shift + Enter for a new line · {modKeyLabel}K for commands
                        </p>
                    </div>
                </div>

                {/* ── Workbench: everything that is not the conversation ── */}
                {panelTab && (
                    <>
                        <div className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm xl:hidden" onClick={() => setPanelTab(null)} aria-hidden="true" />
                        <aside aria-label="Brain workbench" className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[420px] shrink-0 flex-col border-l border-white/[0.07] bg-[#080c14] xl:static xl:z-auto xl:w-[400px]">
                            <div className="flex h-12 shrink-0 items-center gap-1 border-b border-white/[0.07] pl-2 pr-2">
                                {WORKBENCH_TABS.map(tab => (
                                    <button
                                        key={tab.id}
                                        type="button"
                                        onClick={() => setPanelTab(tab.id)}
                                        className={cn(
                                            'rounded-md px-2 py-1.5 text-[10px] font-bold uppercase tracking-[0.08em] transition-colors',
                                            panelTab === tab.id ? 'bg-white/[0.07] text-white' : 'text-slate-500 hover:text-slate-200',
                                        )}
                                    >
                                        {tab.short}
                                    </button>
                                ))}
                                <IconButton onClick={() => setPanelTab(null)} label="Close the workbench" className="ml-auto"><X className="h-4 w-4" /></IconButton>
                            </div>

                            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
                                {panelTab === 'library' && (
                                    <>
                                        <PanelSection icon={Database} tone="text-cyan-300" title="Index" action={<IconButton onClick={() => void refresh()} label="Refresh library status"><RefreshCw className="h-3.5 w-3.5" /></IconButton>}>
                                            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                                                <div><dt className="text-slate-500">Sources</dt><dd className="mt-0.5 font-semibold text-white">{formatCount(counts.sources)}</dd></div>
                                                <div><dt className="text-slate-500">Passages</dt><dd className="mt-0.5 font-semibold text-white">{formatCount(embeddings.total ?? counts.chunks)}</dd></div>
                                                <div><dt className="text-slate-500">Semantic index</dt><dd className={cn('mt-0.5 font-semibold', allEmbedded ? 'text-emerald-300' : 'text-amber-300')}>{formatPercent(embeddings.coverage)}</dd></div>
                                                <div><dt className="text-slate-500">Storage</dt><dd className="mt-0.5 font-semibold text-white">{status?.storage === 'postgres_pgvector' ? 'Supabase' : 'Local'}</dd></div>
                                            </dl>
                                            <div className="mt-4 grid grid-cols-2 gap-2">
                                                {!drive?.connected || drive.connectionState === 'read_only'
                                                    ? <Button type="button" tone="primary" onClick={() => void connectDrive()} disabled={!ready}><Cloud className="h-3.5 w-3.5" /> {drive?.connected ? 'Reconnect' : 'Connect'}</Button>
                                                    : <Button type="button" onClick={() => void syncDrive()} disabled={!ready}><FolderSync className="h-3.5 w-3.5" /> Sync Drive</Button>}
                                                <Button type="button" tone="success" onClick={() => void embedMissing()} disabled={!ready || (embeddings.missing ?? 0) === 0}><Sparkles className="h-3.5 w-3.5" /> {embeddings.missing ? `Embed ${formatCount(embeddings.missing)}` : 'All embedded'}</Button>
                                            </div>
                                            {drive?.connectionState === 'needs_reconnect' && <p className="mt-2 text-xs leading-5 text-amber-300">{drive.connectionMessage ?? 'Google Drive authorization expired. Reconnect to sync new files.'}</p>}
                                            {drive?.connectionState === 'read_only' && <p className="mt-2 text-xs leading-5 text-amber-300">{drive.connectionMessage ?? 'Google Drive is connected read-only, so filings cannot be saved to it. Reconnect to grant file-write permission.'}</p>}
                                            {drive?.connected && drive.writeScope === true && <p className="mt-2 text-[10px] font-medium uppercase tracking-[0.08em] text-emerald-400">Saving to Drive enabled</p>}
                                            {drive?.folderUrl && <a href={drive.folderUrl} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-emerald-300">Open Drive folder <ExternalLink className="h-3.5 w-3.5" /></a>}
                                        </PanelSection>

                                        {portfolioContext && (
                                            <PanelSection icon={BriefcaseBusiness} tone="text-cyan-300" title={portfolioModeLabel} action={<span className={cn('text-[9px] font-bold uppercase tracking-[0.08em]', portfolioContext.marketDataAvailable ? portfolioContext.fresh ? 'text-emerald-300' : 'text-amber-300' : 'text-violet-300')}>{portfolioContext.marketDataAvailable ? `As of ${portfolioContext.dataAsOf ?? 'unknown'}` : 'No market fetch'}</span>}>
                                                <dl className="grid grid-cols-4 gap-2 text-[10px]">
                                                    <div><dt className="text-slate-600">Long</dt><dd className="mt-0.5 font-semibold text-emerald-300">{formatPercent(displayedExposure?.long)}</dd></div>
                                                    <div><dt className="text-slate-600">Short</dt><dd className="mt-0.5 font-semibold text-rose-300">{formatPercent(displayedExposure?.short)}</dd></div>
                                                    <div><dt className="text-slate-600">Gross</dt><dd className="mt-0.5 font-semibold text-white">{formatPercent(displayedExposure?.gross)}</dd></div>
                                                    <div><dt className="text-slate-600">Net</dt><dd className="mt-0.5 font-semibold text-cyan-200">{formatPercent(displayedExposure?.net)}</dd></div>
                                                </dl>
                                            </PanelSection>
                                        )}
                                    </>
                                )}

                                {panelTab === 'search' && (
                                    <PanelSection icon={Search} tone="text-sky-300" title="Search sources">
                                        <div className="flex gap-2">
                                            <input value={libraryQuery} onChange={event => setLibraryQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void searchLibrary(); }} placeholder="Search your library" className="h-9 min-w-0 flex-1 rounded-md border border-white/[0.09] bg-white/[0.025] px-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-sky-500/35" />
                                            <Button type="button" onClick={() => void searchLibrary()} disabled={!ready || !libraryQuery.trim() || isSearching} className="min-h-9 px-2.5" aria-label="Search library">{isSearching ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}</Button>
                                        </div>
                                        {librarySearch && (
                                            <div className="mt-3 border-t border-white/[0.07] pt-3">
                                                <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">{librarySearch.label} · {librarySearch.results.length}</p>
                                                <div className="mt-2 space-y-2">
                                                    {librarySearch.results.length ? librarySearch.results.slice(0, 8).map(result => {
                                                        const link = sourceLink(result.source);
                                                        return <article key={`${result.entityType}-${result.entityId}`} className="rounded-md border border-white/[0.06] bg-black/15 px-3 py-2.5"><div className="flex items-start justify-between gap-2"><p className="min-w-0 text-xs font-semibold leading-5 text-slate-200">{sourceName(result.source, result.title)}</p>{link && <a href={link} target="_blank" rel="noreferrer" className="shrink-0 text-slate-500 hover:text-sky-300"><ArrowUpRight className="h-3.5 w-3.5" /></a>}</div><p className="mt-1 text-[11px] leading-5 text-slate-500">{excerpt(result.body, 125)}</p></article>;
                                                    }) : <p className="text-xs text-slate-500">No matching passages.</p>}
                                                </div>
                                            </div>
                                        )}
                                    </PanelSection>
                                )}

                                {panelTab === 'filings' && (
                                    <PanelSection
                                        icon={FileSearch}
                                        tone="text-violet-300"
                                        title="Filing finder"
                                        action={(
                                            <div className="flex items-center gap-0.5 rounded-md border border-white/[0.08] p-0.5">
                                                {([['sec', 'SEC'], ['espi', 'ESPI/EBI']] as const).map(([value, label]) => (
                                                    <button
                                                        key={value}
                                                        type="button"
                                                        onClick={() => setFilingSource(value)}
                                                        className={cn(
                                                            'rounded px-2 py-1 text-[9px] font-bold uppercase tracking-[0.08em] transition-colors',
                                                            filingSource === value ? 'bg-violet-500/20 text-violet-200' : 'text-slate-500 hover:text-slate-300',
                                                        )}
                                                    >
                                                        {label}
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                    >
                                    {filingSource === 'espi' ? (
                                        <div className="space-y-3">
                                            {/* The PAP listing is addressed by date, so the digest is what it does
                                                natively: what the book's own issuers filed. The phrase search is the
                                                site's own `search=` parameter. */}
                                            <div className="flex flex-wrap items-center gap-1.5">
                                                {[3, 7, 30].map(days => (
                                                    <button
                                                        key={days}
                                                        type="button"
                                                        onClick={() => { setEspiDays(days); void loadEspiDigest(days); }}
                                                        disabled={!ready || isEspiLoading}
                                                        className={cn(
                                                            'rounded-md border px-2 py-1.5 text-[10px] font-semibold transition-colors disabled:cursor-not-allowed disabled:text-slate-600',
                                                            espiDays === days && espiListing?.queriedTickers
                                                                ? 'border-violet-500/30 bg-violet-500/[0.1] text-violet-200'
                                                                : 'border-white/[0.09] text-slate-400 hover:text-slate-200',
                                                        )}
                                                    >
                                                        My book · {days}d
                                                    </button>
                                                ))}
                                                {isEspiLoading && <LoaderCircle className="h-3.5 w-3.5 animate-spin text-violet-300" />}
                                            </div>
                                            <div className="flex gap-2">
                                                <input
                                                    value={espiQuery}
                                                    onChange={event => setEspiQuery(event.target.value)}
                                                    onKeyDown={event => { if (event.key === 'Enter') void searchEspi(); }}
                                                    aria-label="Search ESPI/EBI"
                                                    placeholder="Szukaj spółki, np. LPP"
                                                    className="h-10 min-w-0 flex-1 rounded-md border border-white/[0.09] bg-white/[0.025] px-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-violet-500/35"
                                                />
                                                <Button type="button" tone="primary" onClick={() => void searchEspi()} disabled={!ready || !espiQuery.trim() || isEspiLoading} className="min-h-10 shrink-0 px-3" aria-label="Search ESPI/EBI">
                                                    <Search className="h-3.5 w-3.5" />
                                                </Button>
                                            </div>

                                            {espiListing?.unresolved?.length ? (
                                                <p className="rounded-md border border-amber-400/15 bg-amber-400/[0.04] px-3 py-2 text-[11px] leading-5 text-amber-200/80">
                                                    No issuer name resolved yet for {espiListing.unresolved.join(', ')}, so those holdings are not searched. They fill in once the market data provider answers.
                                                </p>
                                            ) : null}
                                            {espiListing?.failures && Object.keys(espiListing.failures).length ? (
                                                <p className="rounded-md border border-rose-400/15 bg-rose-400/[0.04] px-3 py-2 text-[11px] leading-5 text-rose-200/80">
                                                    {Object.keys(espiListing.failures).join(', ')} could not be queried this time.
                                                </p>
                                            ) : null}
                                            {espiListing?.truncated ? (
                                                <p className="text-[10px] leading-4 text-amber-200/70">
                                                    Stopped at the page limit — there may be more filings than shown.
                                                </p>
                                            ) : null}

                                            <div className="space-y-2">
                                                {(espiListing?.entries ?? []).map(entry => {
                                                    const report = espiReports[entry.nodeId];
                                                    const open = espiOpenNode === entry.nodeId;
                                                    return (
                                                        <article key={entry.nodeId} className="rounded-md border border-white/[0.06] bg-black/15">
                                                            <div className="px-3 py-2.5">
                                                                <div className="flex items-start justify-between gap-2">
                                                                    <div className="min-w-0">
                                                                        <div className="flex flex-wrap items-center gap-1.5">
                                                                            <span className={cn(
                                                                                'rounded border px-1.5 py-0.5 text-[9px] font-bold tracking-[0.06em]',
                                                                                entry.source === 'EBI' ? 'border-sky-400/25 bg-sky-400/[0.08] text-sky-200' : 'border-violet-400/25 bg-violet-400/[0.08] text-violet-200',
                                                                            )}>{entry.source}</span>
                                                                            {entry.matchedTicker && (
                                                                                <span className="rounded border border-emerald-400/25 bg-emerald-400/[0.08] px-1.5 py-0.5 font-mono text-[9px] font-bold text-emerald-200">{entry.matchedTicker}</span>
                                                                            )}
                                                                            <span className="font-mono text-[10px] text-slate-500">{entry.date} {entry.time}</span>
                                                                            {entry.number && <span className="font-mono text-[10px] text-slate-600">{entry.number}</span>}
                                                                        </div>
                                                                        <p className="mt-1 truncate text-xs font-semibold text-slate-200">{entry.issuer ?? 'Unknown issuer'}</p>
                                                                        <p className="mt-0.5 text-[11px] leading-5 text-slate-400">{entry.subject}</p>
                                                                    </div>
                                                                    <div className="flex shrink-0 items-center gap-1">
                                                                        <a href={entry.url} target="_blank" rel="noreferrer" className="p-1.5 text-slate-600 transition-colors hover:text-violet-300" aria-label="Open at PAP"><ArrowUpRight className="h-3.5 w-3.5" /></a>
                                                                        <Button type="button" onClick={() => void toggleEspiReport(entry.nodeId)} className="min-h-7 px-2 text-[9px]">{open ? 'Hide' : 'Open'}</Button>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                            {open && (
                                                                <div className="border-t border-white/[0.06] px-3 py-2.5">
                                                                    {!report ? (
                                                                        <p className="flex items-center gap-2 text-[11px] text-slate-500"><LoaderCircle className="h-3.5 w-3.5 animate-spin" /> Reading the report…</p>
                                                                    ) : (
                                                                        <div className="space-y-2.5">
                                                                            <p className="text-[10px] leading-4 text-slate-500">
                                                                                {[report.reportType, report.issuerSymbol, report.preparedOn, report.sector].filter(Boolean).join(' · ')}
                                                                            </p>
                                                                            {report.financials?.items?.length ? (
                                                                                <div className="overflow-x-auto">
                                                                                    <table className="w-full text-[10px]">
                                                                                        <caption className="pb-1 text-left text-[10px] text-slate-500">
                                                                                            Wybrane dane {[report.financials.units, report.financials.currency].filter(Boolean).join(' ')}
                                                                                        </caption>
                                                                                        <thead><tr className="text-slate-600">
                                                                                            <th className="py-1 text-left font-semibold">Pozycja</th>
                                                                                            <th className="whitespace-nowrap py-1 pl-2 text-right font-semibold">teraz</th>
                                                                                            <th className="whitespace-nowrap py-1 pl-2 text-right font-semibold">poprzednio</th>
                                                                                        </tr></thead>
                                                                                        <tbody>
                                                                                            {report.financials.items.slice(0, 8).map(row => (
                                                                                                <tr key={row.item} className="border-t border-white/[0.05]">
                                                                                                    <td className="py-1 pr-2 text-slate-300">{row.item}</td>
                                                                                                    <td className="whitespace-nowrap py-1 pl-2 text-right font-mono tabular-nums text-slate-100">{typeof row.current === 'number' ? row.current.toLocaleString('pl-PL') : '—'}</td>
                                                                                                    <td className="whitespace-nowrap py-1 pl-2 text-right font-mono tabular-nums text-slate-500">{typeof row.previous === 'number' ? row.previous.toLocaleString('pl-PL') : '—'}</td>
                                                                                                </tr>
                                                                                            ))}
                                                                                        </tbody>
                                                                                    </table>
                                                                                </div>
                                                                            ) : null}
                                                                            {report.attachments?.length ? (
                                                                                <div className="space-y-1.5">
                                                                                    {report.attachments.map(file => (
                                                                                        <div key={file.url} className="flex items-center justify-between gap-2">
                                                                                            <a href={file.url} target="_blank" rel="noreferrer" className="min-w-0 truncate text-[11px] text-slate-300 transition-colors hover:text-violet-200">{file.fileName}</a>
                                                                                            <Button type="button" onClick={() => void importUrl(file.url, `${report.issuerSymbol ?? entry.issuer ?? ''} ${entry.subject}`.trim(), true)} disabled={isAgentWorking} className="min-h-7 shrink-0 px-2 text-[9px]">Add</Button>
                                                                                        </div>
                                                                                    ))}
                                                                                </div>
                                                                            ) : (
                                                                                <p className="text-[11px] text-slate-500">No attachments on this report.</p>
                                                                            )}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            )}
                                                        </article>
                                                    );
                                                })}
                                                {espiListing && !(espiListing.entries ?? []).length && !isEspiLoading && (
                                                    <p className="text-xs leading-5 text-slate-500">{espiListing.message ?? 'Nothing filed in this window.'}</p>
                                                )}
                                                {!espiListing && !isEspiLoading && (
                                                    <p className="text-xs leading-5 text-slate-500">Pick a window to see what your Polish holdings filed, or search for a company.</p>
                                                )}
                                            </div>
                                        </div>
                                    ) : (
                                        <>
                                        <div className="flex gap-2">
                                            <input
                                                value={agentTask}
                                                onChange={event => { setAgentTask(event.target.value); setAgentSearch(null); setAgentCandidates([]); }}
                                                onKeyDown={event => { if (event.key === 'Enter') void findOfficialSources(); }}
                                                aria-label="Find an official filing"
                                                className="h-10 min-w-0 flex-1 rounded-md border border-white/[0.09] bg-white/[0.025] px-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-violet-500/35"
                                                placeholder="META 2025 10-K"
                                            />
                                            <Button type="button" tone="primary" onClick={() => void findOfficialSources()} disabled={!ready || !agentTask.trim() || isAgentWorking} className="min-h-10 shrink-0 px-3" aria-label="Search SEC filings">
                                                {isAgentWorking ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                                            </Button>
                                        </div>

                                        {agentSearch && (
                                            <div className="mt-3 border-t border-white/[0.07] pt-3">
                                                <div className="flex flex-wrap items-center gap-1.5">
                                                    {agentSearch.resolvedCompany?.ticker && <span className="rounded border border-violet-400/20 bg-violet-400/[0.08] px-2 py-1 font-mono text-[10px] font-bold text-violet-200">{agentSearch.resolvedCompany.ticker}</span>}
                                                    {(agentSearch.intent?.requestedForms ?? []).map(form => <span key={form} className="rounded border border-white/[0.08] px-2 py-1 text-[9px] font-bold uppercase text-slate-400">{form}</span>)}
                                                    {(agentSearch.intent?.requestedYears ?? []).map(year => <span key={year} className="rounded border border-white/[0.08] px-2 py-1 text-[9px] font-bold uppercase text-slate-400">FY {year}</span>)}
                                                    {agentSearch.intent?.requestedQuarter && <span className="rounded border border-white/[0.08] px-2 py-1 text-[9px] font-bold uppercase text-slate-400">Q{agentSearch.intent.requestedQuarter}</span>}
                                                </div>
                                                <p className="mt-2 text-[11px] leading-5 text-slate-500">{agentSearch.message}</p>
                                            </div>
                                        )}

                                        {agentCandidates.length > 0 && (
                                            <div className="mt-3 border-t border-white/[0.07] pt-3">
                                                <div className="space-y-2">
                                                    {agentCandidates.slice(0, 8).map(candidate => (
                                                        <article key={candidate.url} className={cn('rounded-md border bg-black/15 px-3 py-3', candidate.isBestMatch && candidate.isExactMatch ? 'border-emerald-400/25' : 'border-white/[0.06]')}>
                                                            <div className="flex items-start justify-between gap-3">
                                                                <a href={candidate.url} target="_blank" rel="noreferrer" className="min-w-0 text-xs font-semibold leading-5 text-slate-100 transition-colors hover:text-violet-200">{candidate.title}</a>
                                                                <Button type="button" onClick={() => void importUrl(candidate.url, candidate.title, true)} disabled={isAgentWorking} className="min-h-7 shrink-0 px-2 text-[9px]">Add</Button>
                                                            </div>
                                                            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-500">
                                                                <span className={candidate.isExactMatch ? 'font-semibold text-emerald-300' : 'text-slate-400'}>{candidate.matchQuality ?? 'Official filing'}</span>
                                                                {candidate.periodLabel && <span>{candidate.periodLabel}</span>}
                                                                {candidate.filingDate && <span>Filed {candidate.filingDate}</span>}
                                                                {candidate.isAmendment && <span>Amended</span>}
                                                            </div>
                                                            {candidate.matchReasons?.length ? <p className="mt-1 text-[10px] leading-4 text-slate-600">{candidate.matchReasons.join(' · ')}</p> : null}
                                                        </article>
                                                    ))}
                                                </div>
                                                <Button type="button" tone="success" onClick={() => void runAndImport()} disabled={!ready || isAgentWorking || agentCandidates.length === 0} className="mt-3 w-full"><Sparkles className="h-3.5 w-3.5" /> Import top match</Button>
                                            </div>
                                        )}

                                        {agentSearch && agentCandidates.length === 0 && <p className="mt-3 rounded-md border border-amber-400/15 bg-amber-400/[0.04] px-3 py-2 text-xs leading-5 text-amber-200/80">No matching SEC filing was returned. Check the company or reporting period.</p>}

                                        <div className="mt-4 flex gap-2 border-t border-white/[0.07] pt-3">
                                            <input value={agentUrl} onChange={event => setAgentUrl(event.target.value)} className="h-9 min-w-0 flex-1 rounded-md border border-white/[0.09] bg-white/[0.025] px-3 text-xs text-white outline-none placeholder:text-slate-600 focus:border-violet-500/35" placeholder="Import public URL" />
                                            <Button type="button" onClick={() => void importUrl(agentUrl)} disabled={!ready || !agentUrl.trim() || isAgentWorking} className="min-h-9 px-2.5" aria-label="Import public URL"><Plus className="h-3.5 w-3.5" /></Button>
                                        </div>
                                        </>
                                    )}
                                    </PanelSection>
                                )}

                                {panelTab === 'drive' && (
                                    <>
                                        <BrainFilesByDate disabled={backendState !== 'ready'} />
                                        <BrainDriveCoverage disabled={backendState !== 'ready'} />
                                    </>
                                )}

                                {panelTab === 'code' && <BrainSelfBuild disabled={backendState !== 'ready'} />}
                            </div>
                        </aside>
                    </>
                )}
            </div>

            {/* ── Status bar: the state an editor keeps at the bottom, not in cards ── */}
            <footer className="flex h-7 shrink-0 items-center gap-3 border-t border-white/[0.07] bg-[#080c14] px-3 text-[10px] text-slate-500">
                <span className="inline-flex shrink-0 items-center gap-1.5">
                    <span className={cn('h-1.5 w-1.5 rounded-full', ready ? allEmbedded ? 'bg-emerald-400' : 'bg-amber-400' : 'bg-rose-400')} />
                    <span className={cn('font-semibold', ready ? 'text-slate-300' : 'text-rose-300')}>{ready ? libraryState : backendState === 'checking' ? 'Checking Brain' : 'Backend offline'}</span>
                </span>
                <button type="button" onClick={() => setPanelTab('library')} className="hidden shrink-0 transition-colors hover:text-slate-200 sm:inline">
                    {formatCount(counts.sources)} sources · {formatPercent(embeddings.coverage)} indexed
                </button>
                {portfolioContext && (
                    <button type="button" onClick={() => setPanelTab('library')} className="hidden shrink-0 transition-colors hover:text-slate-200 md:inline">
                        {portfolioContext.positionCount ?? 0} positions · {formatPercent(displayedExposure?.gross)} {portfolioContext.marketDataAvailable ? 'gross' : 'target gross'}
                    </button>
                )}
                {conversationAutosave?.status === 'failed' || conversationAutosave?.status === 'unavailable' ? (
                    <span className="shrink-0 text-amber-300" title={conversationAutosave.reason ?? 'Drive autosave failed'}>Autosave failed</span>
                ) : drive?.connected ? (
                    <span className="hidden shrink-0 lg:inline">Autosave on</span>
                ) : null}
                {/* Every failure in this file reports here, so it must stay readable on any width. */}
                {notice && <span className="ml-auto truncate pl-3 text-right text-slate-400" title={notice}>{notice}</span>}
            </footer>

            {isPaletteOpen && (
                <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/75 p-4 pt-[12vh] backdrop-blur-sm" onClick={() => setIsPaletteOpen(false)}>
                    <section role="dialog" aria-modal="true" aria-label="Brain commands" onClick={event => event.stopPropagation()} className="flex max-h-[min(560px,calc(100vh-160px))] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-white/[0.12] bg-[#0a0f18] shadow-2xl">
                        <div className="flex items-center gap-2 border-b border-white/[0.08] px-4">
                            <Command className="h-4 w-4 shrink-0 text-slate-500" />
                            <input
                                autoFocus
                                value={paletteQuery}
                                onChange={event => setPaletteQuery(event.target.value)}
                                onKeyDown={event => {
                                    if (event.key !== 'Enter') return;
                                    const first = paletteMatches[0];
                                    if (!first || first.disabled) return;
                                    setIsPaletteOpen(false);
                                    first.run();
                                }}
                                placeholder="Type a command…"
                                aria-label="Search Brain commands"
                                className="h-12 min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-600"
                            />
                        </div>
                        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
                            {paletteMatches.length ? paletteMatches.map(command => (
                                <button
                                    key={command.id}
                                    type="button"
                                    disabled={command.disabled}
                                    onClick={() => { setIsPaletteOpen(false); command.run(); }}
                                    className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-40"
                                >
                                    <command.icon className="h-4 w-4 shrink-0 text-slate-500" />
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate text-xs font-semibold text-slate-200">{command.label}</span>
                                        {command.hint && <span className="mt-0.5 block truncate text-[10px] text-slate-600">{command.hint}</span>}
                                    </span>
                                    <span className="shrink-0 text-[9px] font-bold uppercase tracking-[0.08em] text-slate-700">{command.group}</span>
                                </button>
                            )) : (
                                <p className="px-3 py-6 text-center text-xs text-slate-600">No command matches that.</p>
                            )}
                        </div>
                    </section>
                </div>
            )}
            {isReferencePickerOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
                    <section role="dialog" aria-modal="true" aria-labelledby="reference-layer-title" className="flex max-h-[min(720px,calc(100vh-32px))] w-full max-w-2xl flex-col rounded-lg border border-white/[0.12] bg-[#0a0f18] shadow-2xl">
                        <div className="flex items-start justify-between gap-4 border-b border-white/[0.08] px-5 py-4">
                            <div>
                                <div className="flex items-center gap-2"><BookOpenCheck className="h-4 w-4 text-violet-300" /><h2 id="reference-layer-title" className="text-sm font-bold text-white">Persistent reference layer</h2></div>
                                <p className="mt-1 text-xs leading-5 text-slate-400">Choose up to {referenceLimit} files. Each future question receives a relevant passage from every selected source as a standing investing framework.</p>
                            </div>
                            <button type="button" onClick={closeReferencePicker} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-white/10 text-slate-400 transition-colors hover:bg-white/[0.07] hover:text-white" aria-label="Close reference source picker"><X className="h-4 w-4" /></button>
                        </div>
                        <div className="border-b border-white/[0.08] px-5 py-3">
                            <div className="flex items-center gap-2 rounded-md border border-white/[0.09] bg-white/[0.025] px-3 focus-within:border-violet-500/35"><Search className="h-3.5 w-3.5 text-slate-500" /><input value={referenceFilter} onChange={event => setReferenceFilter(event.target.value)} aria-label="Filter reference sources" placeholder="Find a file in your indexed Drive library" className="h-9 min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-600" /></div>
                        </div>
                        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
                            {isReferenceLoading ? (
                                <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-slate-500"><LoaderCircle className="h-4 w-4 animate-spin text-violet-300" /> Loading indexed research files...</div>
                            ) : filteredReferenceSources.length ? (
                                <div className="divide-y divide-white/[0.06]">
                                    {filteredReferenceSources.map(source => {
                                        if (typeof source.id !== 'number') return null;
                                        const selected = referenceSelection.includes(source.id);
                                        const metadataPath = source.metadata?.relativePath;
                                        const detail = source.relativePath
                                            ?? (typeof metadataPath === 'string' ? metadataPath : undefined)
                                            ?? source.kind
                                            ?? 'Indexed source';
                                        return (
                                            <label key={source.id} className={cn('flex cursor-pointer items-start gap-3 py-3 transition-colors', selected ? 'text-white' : 'text-slate-300')}>
                                                <input type="checkbox" checked={selected} onChange={() => toggleReferenceSource(source.id!)} className="mt-0.5 h-4 w-4 shrink-0 accent-violet-400" />
                                                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{sourceName(source)}</p><p className="mt-0.5 truncate text-xs text-slate-500">{detail}</p></div>
                                                {sourceLink(source) && <a href={sourceLink(source)} target="_blank" rel="noreferrer" onClick={event => event.stopPropagation()} className="mt-0.5 shrink-0 text-slate-500 transition-colors hover:text-violet-300" aria-label={`Open ${sourceName(source)}`}><ArrowUpRight className="h-3.5 w-3.5" /></a>}
                                            </label>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div className="flex min-h-40 items-center justify-center text-sm text-slate-500">No indexed sources match this search.</div>
                            )}
                        </div>
                        <div className="flex items-center justify-between gap-3 border-t border-white/[0.08] px-5 py-3">
                            <p className="text-xs text-slate-500"><span className="font-semibold text-violet-200">{referenceSelection.length}/{referenceLimit}</span> sources active in every answer</p>
                            <div className="flex gap-2"><Button type="button" onClick={closeReferencePicker}>Cancel</Button><Button type="button" tone="primary" onClick={() => void saveReferenceSet(referenceSelection, true)} disabled={isReferenceSaving}>{isReferenceSaving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <BookOpenCheck className="h-3.5 w-3.5" />} Save layer</Button></div>
                        </div>
                    </section>
                </div>
            )}
            {isFullContextPickerOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
                    <section role="dialog" aria-modal="true" aria-labelledby="full-context-title" className="flex max-h-[min(720px,calc(100vh-32px))] w-full max-w-2xl flex-col rounded-lg border border-white/[0.12] bg-[#0a0f18] shadow-2xl">
                        <div className="flex items-start justify-between gap-4 border-b border-white/[0.08] px-5 py-4">
                            <div>
                                <div className="flex items-center gap-2"><FileSearch className="h-4 w-4 text-cyan-300" /><h2 id="full-context-title" className="text-sm font-bold text-white">Full-document context</h2></div>
                                <p className="mt-1 text-xs leading-5 text-slate-400">Choose up to {fullContextLimit} indexed files. Their full extracted text is included in every future answer, subject to {formatCount(fullContextMaxChars)} characters per file and {formatCount(fullContextTotalMaxChars)} characters total. This is more deliberate than retrieval and can take longer.</p>
                            </div>
                            <button type="button" onClick={closeFullContextPicker} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-white/10 text-slate-400 transition-colors hover:bg-white/[0.07] hover:text-white" aria-label="Close full-document source picker"><X className="h-4 w-4" /></button>
                        </div>
                        <div className="border-b border-white/[0.08] px-5 py-3">
                            <div className="flex items-center gap-2 rounded-md border border-white/[0.09] bg-white/[0.025] px-3 focus-within:border-cyan-500/35"><Search className="h-3.5 w-3.5 text-slate-500" /><input value={fullContextFilter} onChange={event => setFullContextFilter(event.target.value)} aria-label="Filter full-document sources" placeholder="Find a file in your indexed Drive library" className="h-9 min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-600" /></div>
                        </div>
                        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
                            {isFullContextLoading ? (
                                <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-slate-500"><LoaderCircle className="h-4 w-4 animate-spin text-cyan-300" /> Loading indexed research files...</div>
                            ) : filteredFullContextSources.length ? (
                                <div className="divide-y divide-white/[0.06]">
                                    {filteredFullContextSources.map(source => {
                                        if (typeof source.id !== 'number') return null;
                                        const selected = fullContextSelection.includes(source.id);
                                        const metadataPath = source.metadata?.relativePath;
                                        const detail = source.relativePath
                                            ?? (typeof metadataPath === 'string' ? metadataPath : undefined)
                                            ?? source.kind
                                            ?? 'Indexed source';
                                        return (
                                            <label key={source.id} className={cn('flex cursor-pointer items-start gap-3 py-3 transition-colors', selected ? 'text-white' : 'text-slate-300')}>
                                                <input type="checkbox" checked={selected} onChange={() => toggleFullContextSource(source.id!)} className="mt-0.5 h-4 w-4 shrink-0 accent-cyan-400" />
                                                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{sourceName(source)}</p><p className="mt-0.5 truncate text-xs text-slate-500">{detail}</p></div>
                                                {sourceLink(source) && <a href={sourceLink(source)} target="_blank" rel="noreferrer" onClick={event => event.stopPropagation()} className="mt-0.5 shrink-0 text-slate-500 transition-colors hover:text-cyan-300" aria-label={`Open ${sourceName(source)}`}><ArrowUpRight className="h-3.5 w-3.5" /></a>}
                                            </label>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div className="flex min-h-40 items-center justify-center text-sm text-slate-500">No indexed sources match this search.</div>
                            )}
                        </div>
                        <div className="flex flex-col gap-3 border-t border-white/[0.08] px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
                            <p className="text-xs text-slate-500"><span className="font-semibold text-cyan-200">{fullContextSelection.length}/{fullContextLimit}</span> whole files in every answer</p>
                            <div className="flex gap-2"><Button type="button" onClick={closeFullContextPicker}>Cancel</Button><Button type="button" tone="success" onClick={() => void saveFullContextSet(fullContextSelection, true)} disabled={isFullContextSaving}>{isFullContextSaving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <FileSearch className="h-3.5 w-3.5" />} Save full context</Button></div>
                        </div>
                    </section>
                </div>
            )}
            {isSystemPromptOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
                    <section role="dialog" aria-modal="true" aria-labelledby="system-prompt-title" className="flex max-h-[min(720px,calc(100vh-32px))] w-full max-w-2xl flex-col rounded-lg border border-white/[0.12] bg-[#0a0f18] shadow-2xl">
                        <div className="flex items-start justify-between gap-4 border-b border-white/[0.08] px-5 py-4">
                            <div>
                                <div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-amber-300" /><h2 id="system-prompt-title" className="text-sm font-bold text-white">AI system prompt</h2></div>
                                <p className="mt-1 text-xs leading-5 text-slate-400">This is sent to Gemini as the system instruction for every answer. Your selected reference files are injected separately into the same model context.</p>
                            </div>
                            <button type="button" onClick={closeSystemPrompt} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-white/10 text-slate-400 transition-colors hover:bg-white/[0.07] hover:text-white" aria-label="Close AI system prompt"><X className="h-4 w-4" /></button>
                        </div>
                        <div className="min-h-0 flex-1 px-5 py-4">
                            {isSystemPromptLoading ? (
                                <div className="flex min-h-64 items-center justify-center gap-2 text-sm text-slate-500"><LoaderCircle className="h-4 w-4 animate-spin text-amber-300" /> Loading system instructions...</div>
                            ) : (
                                <textarea value={systemPrompt} onChange={event => setSystemPrompt(event.target.value)} maxLength={systemPromptLimit} aria-label="AI system prompt" className="min-h-[320px] w-full resize-none rounded-md border border-white/[0.1] bg-black/20 px-4 py-3 font-mono text-xs leading-6 text-slate-100 outline-none placeholder:text-slate-600 focus:border-amber-500/35" placeholder="Describe how the Investment Brain should reason, challenge assumptions, and communicate." />
                            )}
                        </div>
                        <div className="flex flex-col gap-3 border-t border-white/[0.08] px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
                            <div className="flex items-center gap-3"><p className="text-xs text-slate-500">{systemPrompt.length.toLocaleString()}/{systemPromptLimit.toLocaleString()} characters</p><button type="button" onClick={() => setSystemPrompt(defaultSystemPrompt)} disabled={!defaultSystemPrompt || isSystemPromptLoading} className="text-xs font-semibold text-amber-200 transition-colors hover:text-amber-100 disabled:text-slate-600">Reset default</button></div>
                            <div className="flex gap-2"><Button type="button" onClick={closeSystemPrompt}>Cancel</Button><Button type="button" tone="primary" onClick={() => void saveSystemPrompt()} disabled={isSystemPromptLoading || isSystemPromptSaving}>{isSystemPromptSaving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Save prompt</Button></div>
                        </div>
                    </section>
                </div>
            )}
        </div>
    );
};
