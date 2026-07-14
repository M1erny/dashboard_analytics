import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    ArrowLeft,
    ArrowUpRight,
    BrainCircuit,
    BookOpenCheck,
    ChevronDown,
    Cloud,
    ExternalLink,
    FileSearch,
    FolderSync,
    Library,
    LoaderCircle,
    MessageSquare,
    Plus,
    RefreshCw,
    Search,
    Send,
    Sparkles,
    X,
} from 'lucide-react';
import { cn } from '../lib/utils';

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
    connectionState?: 'ready' | 'needs_reconnect' | 'not_configured';
    connectionMessage?: string;
    writeScope?: boolean;
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

type RetrievalDiagnostics = {
    semanticHits?: number;
    keywordHits?: number;
    mergedHits?: number;
    expandedFiles?: number;
    semanticAvailable?: boolean;
    referenceSources?: number;
    referenceSemanticHits?: number;
    fullDocuments?: number;
    fullContextChars?: number;
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
    timings?: { totalMs?: number; generationMs?: number; semanticError?: string; keywordError?: string };
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
};

type LibrarySearch = {
    label: string;
    results: SearchResult[];
};

const DEFAULT_BRAIN_API_URL = 'https://dashboard-eo6k.onrender.com';
const API_BASE = (
    import.meta.env.VITE_BRAIN_API_URL
    ?? import.meta.env.VITE_API_URL
    ?? DEFAULT_BRAIN_API_URL
).replace(/\/$/, '');

const api = (path: string) => `${API_BASE}${path}`;
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
                <ul key={`l-${index}`} className="space-y-1.5 pl-5 text-sm leading-6 text-slate-200 marker:text-emerald-300">
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
            'inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors disabled:cursor-not-allowed disabled:border-white/[0.08] disabled:bg-white/[0.025] disabled:text-slate-600',
            tone === 'primary' && 'border-emerald-500/35 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/25',
            tone === 'success' && 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100 hover:bg-cyan-500/20',
            tone === 'quiet' && 'border-white/10 bg-white/[0.035] text-slate-300 hover:bg-white/[0.07]',
            className,
        )}
    />
);

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
    const [ticker, setTicker] = useState('');
    const [draft, setDraft] = useState('What does my research say about the moat, risks, valuation lens, and what would change my mind?');
    const [thread, setThread] = useState<ChatMessage[]>([]);
    const [isAsking, setIsAsking] = useState(false);
    const [notice, setNotice] = useState('');
    const [libraryQuery, setLibraryQuery] = useState('');
    const [librarySearch, setLibrarySearch] = useState<LibrarySearch | null>(null);
    const [isSearching, setIsSearching] = useState(false);
    const [agentTask, setAgentTask] = useState('');
    const [agentUrl, setAgentUrl] = useState('');
    const [agentCandidates, setAgentCandidates] = useState<AgentCandidate[]>([]);
    const [agentSearch, setAgentSearch] = useState<AgentSearchResponse | null>(null);
    const [isAgentWorking, setIsAgentWorking] = useState(false);
    const outputRef = useRef<HTMLDivElement | null>(null);

    const refresh = async () => {
        try {
            const [statusResult, driveResult, referenceResult, fullContextResult, systemPromptResult] = await Promise.allSettled([
                request(api('/api/brain/status'), {}, 12000),
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
        } catch {
            setBackendState('offline');
        }
    };

    useEffect(() => { void refresh(); }, []);

    useEffect(() => {
        if (thread.length || isAsking) outputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, [thread.length, isAsking]);

    const ready = backendState === 'ready';
    const counts = status?.counts ?? {};
    const embeddings = status?.embeddings ?? {};
    const allEmbedded = (embeddings.missing ?? 0) === 0 && (embeddings.total ?? counts.chunks ?? 0) > 0;
    const libraryState = !ready ? 'Offline' : !drive?.connected ? 'Drive needs access' : !allEmbedded ? 'Embedding pending' : 'Library ready';
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
        const cleanedTicker = ticker.trim().toUpperCase();
        const question = draft.trim();
        if (!ready || !question || isAsking) return;

        const userMessage: ChatMessage = { id: messageId(), role: 'user', content: question };
        const priorConversation = thread.map(message => ({ role: message.role, content: message.content }));
        setThread(current => [...current, userMessage]);
        setDraft('');
        setIsAsking(true);
        setNotice(fullContextSources.length
            ? `Reading ${fullContextSources.length} full document${fullContextSources.length === 1 ? '' : 's'}, then retrieving supporting evidence...`
            : 'Searching evidence, then reading the strongest source files...');

        try {
            const response = await request(api('/api/brain/analyze-company'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticker: cleanedTicker || undefined,
                    question,
                    limit: 6,
                    useSemantic: true,
                    conversation: priorConversation.slice(-10),
                }),
            }, fullContextSources.length ? 120000 : 65000);
            if (!response.ok) throw new Error(await errorText(response, 'The Brain could not complete this question.'));
            const payload = await response.json() as AnalysisResponse;
            setThread(current => [...current, {
                id: messageId(),
                role: 'assistant',
                content: payload.answer,
                context: payload.context,
                retrieval: payload.retrieval,
                timingMs: payload.timings?.totalMs,
                status: payload.timings?.semanticError ? 'Vector retrieval was unavailable; exact search still contributed.' : undefined,
            }]);
            const readCount = payload.retrieval?.expandedFiles ?? 0;
            const fullDocumentCount = payload.retrieval?.fullDocuments ?? 0;
            setNotice(`${payload.model} answered in ${formatSeconds(payload.timings?.totalMs)}${fullDocumentCount ? ` with ${fullDocumentCount} full document${fullDocumentCount === 1 ? '' : 's'} in context` : readCount ? ` after reading ${readCount} source file${readCount === 1 ? '' : 's'}` : ''}.`);
        } catch (error) {
            const text = error instanceof DOMException && error.name === 'AbortError'
                ? 'This request took too long. The backend may be waking up; try the question again.'
                : error instanceof Error ? error.message : 'The Brain could not complete this question.';
            setThread(current => [...current, { id: messageId(), role: 'assistant', content: text, status: 'No new conclusion was generated.' }]);
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
                body: JSON.stringify({ limitFiles: 2000, maxBytes: 10 * 1024 * 1024, changedFilesLimit: 20, force: false }),
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
                body: JSON.stringify({ batchSize: 5, maxChunks: 500, force: false }),
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

    const closeReferencePicker = () => {
        setReferenceSelection(referenceSources.flatMap(source => typeof source.id === 'number' ? [source.id] : []));
        setIsReferencePickerOpen(false);
    };

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

    const closeFullContextPicker = () => {
        setFullContextSelection(fullContextSources.flatMap(source => typeof source.id === 'number' ? [source.id] : []));
        setIsFullContextPickerOpen(false);
    };

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
                    embedAfterImport: true,
                    embedMaxChunks: 120,
                    agentTask: agentTask.trim() || undefined,
                }),
            }, 90000);
            if (!response.ok) throw new Error(await errorText(response, 'Source import failed.'));
            const payload = await response.json() as {
                status?: string;
                chunks?: unknown[];
                driveFile?: { webViewLink?: string };
                document?: { convertedToMarkdown?: boolean };
            };
            setAgentUrl('');
            setNotice(payload.status === 'skipped'
                ? 'That source was already indexed and has not changed.'
                : `Source indexed as ${payload.chunks?.length ?? 0} passages${payload.document?.convertedToMarkdown ? ' in Markdown' : ''}${payload.driveFile?.webViewLink ? ' and saved to Drive' : ''}.`);
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
                    embedMaxChunks: 120,
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

    const resetThread = () => {
        setThread([]);
        setTicker('');
        setDraft('What does my research say about the moat, risks, valuation lens, and what would change my mind?');
        setNotice('New research thread.');
    };

    return (
        <div className="min-h-screen bg-[#06080d] text-foreground">
            <div className="h-px bg-gradient-to-r from-emerald-400 via-cyan-400 to-violet-400" />
            <main className="mx-auto flex min-h-screen max-w-[1500px] flex-col px-4 py-4 sm:px-6 lg:px-8">
                <header className="flex flex-col gap-4 border-b border-white/[0.07] pb-4 md:flex-row md:items-center md:justify-between">
                    <div className="min-w-0">
                        <a href="/" className="inline-flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500 transition-colors hover:text-slate-300">
                            <ArrowLeft className="h-3.5 w-3.5" /> Dashboard
                        </a>
                        <div className="mt-3 flex items-center gap-3">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-emerald-400/20 bg-emerald-400/10">
                                <BrainCircuit className="h-5 w-5 text-emerald-300" />
                            </div>
                            <div className="min-w-0">
                                <h1 className="text-2xl font-bold text-white">Investment Brain</h1>
                                <p className="mt-0.5 text-sm text-slate-400">Ask, inspect the evidence, and keep the thread moving.</p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className={cn('inline-flex min-h-8 items-center gap-2 rounded-md border px-3 text-[10px] font-bold uppercase tracking-[0.1em]', ready ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300')}>
                            <span className={cn('h-1.5 w-1.5 rounded-full', ready ? 'bg-emerald-300' : 'bg-amber-300')} />
                            {ready ? libraryState : backendState === 'checking' ? 'Checking Brain' : 'Backend offline'}
                        </span>
                        <Button type="button" onClick={resetThread} disabled={isAsking}>
                            <Plus className="h-3.5 w-3.5" /> New thread
                        </Button>
                    </div>
                </header>

                <div className="grid flex-1 grid-cols-1 items-start gap-5 py-5 xl:grid-cols-[minmax(0,1fr)_340px]">
                    <section className="flex min-h-[560px] flex-col rounded-lg border border-white/[0.08] bg-[#090e17]/95">
                        <div className="flex items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-3 sm:px-5">
                            <div className="flex min-w-0 items-center gap-2">
                                <MessageSquare className="h-4 w-4 text-emerald-300" />
                                <span className="text-[11px] font-bold uppercase tracking-[0.11em] text-slate-300">Research thread</span>
                            </div>
                            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                                <button
                                    type="button"
                                    onClick={() => void openReferencePicker()}
                                    disabled={!ready}
                                    title={referenceSources.map(source => sourceName(source)).join('\n') || 'Choose files that are always used as a framework'}
                                    className="inline-flex min-h-7 shrink-0 items-center gap-1.5 rounded-md border border-violet-500/20 bg-violet-500/[0.07] px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-violet-200 transition-colors hover:bg-violet-500/[0.13] disabled:cursor-not-allowed disabled:border-white/[0.08] disabled:bg-white/[0.025] disabled:text-slate-600"
                                >
                                    <BookOpenCheck className="h-3.5 w-3.5" />
                                    <span className="hidden sm:inline">Reference </span>{referenceSources.length || 'set'}
                                </button>
                                <button
                                    type="button"
                                    onClick={() => void openFullContextPicker()}
                                    disabled={!ready}
                                    title={fullContextSources.map(source => sourceName(source)).join('\n') || 'Choose up to four indexed files to include in full'}
                                    className="inline-flex min-h-7 shrink-0 items-center gap-1.5 rounded-md border border-cyan-500/20 bg-cyan-500/[0.07] px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-cyan-200 transition-colors hover:bg-cyan-500/[0.13] disabled:cursor-not-allowed disabled:border-white/[0.08] disabled:bg-white/[0.025] disabled:text-slate-600"
                                >
                                    <FileSearch className="h-3.5 w-3.5" />
                                    <span className="hidden sm:inline">Full files </span>{fullContextSources.length || 'set'}
                                </button>
                                {notice && <span className="hidden max-w-[48%] truncate text-right text-[10px] font-medium text-slate-500 sm:inline">{notice}</span>}
                            </div>
                        </div>

                        <div ref={outputRef} className="flex-1 space-y-5 overflow-auto px-4 py-5 sm:px-7">
                            {!thread.length && !isAsking && (
                                <div className="mx-auto flex max-w-2xl flex-col items-start py-12 sm:py-20">
                                    <span className="inline-flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-300"><Sparkles className="h-3.5 w-3.5" /> Evidence-first research</span>
                                    <h2 className="mt-4 text-2xl font-bold leading-tight text-white sm:text-3xl">A second mind for the work that compounds.</h2>
                                    <p className="mt-3 max-w-xl text-sm leading-6 text-slate-400">The Brain retrieves your Drive research by meaning and exact terms, reads the strongest source files around the matches, then keeps sources attached to every answer.</p>
                                    <div className="mt-6 flex flex-wrap gap-2">
                                        {[
                                            'Where does value accrue in AI infrastructure?',
                                            'What is the strongest bear case?',
                                            'Compare this against my historical framework.',
                                        ].map(suggestion => (
                                            <button key={suggestion} type="button" onClick={() => setDraft(suggestion)} className="rounded-md border border-white/[0.09] bg-white/[0.025] px-3 py-2 text-left text-xs text-slate-300 transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/[0.06] hover:text-white">
                                                {suggestion}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {thread.map(message => (
                                <article key={message.id} className={cn('max-w-3xl', message.role === 'user' ? 'ml-auto' : 'mr-auto')}>
                                    <div className={cn('rounded-lg border px-4 py-3.5 sm:px-5', message.role === 'user' ? 'border-sky-500/20 bg-sky-500/[0.08]' : 'border-white/[0.08] bg-white/[0.025]')}>
                                        <div className="mb-3 flex items-center justify-between gap-3">
                                            <span className={cn('text-[10px] font-bold uppercase tracking-[0.12em]', message.role === 'user' ? 'text-sky-300' : 'text-emerald-300')}>
                                                {message.role === 'user' ? 'You' : 'Investment Brain'}
                                            </span>
                                            {message.role === 'assistant' && message.retrieval && (
                                                <span className="text-[10px] font-medium text-slate-500">
                                                    {message.retrieval.semanticAvailable ? `${message.retrieval.semanticHits ?? 0} semantic` : 'exact search'}
                                                    {` + ${message.retrieval.keywordHits ?? 0} exact`}
                                                    {message.retrieval.referenceSources ? ` / ${message.retrieval.referenceSources} framework${message.retrieval.referenceSources === 1 ? '' : 's'}` : ''}
                                                    {message.retrieval.fullDocuments ? ` / ${message.retrieval.fullDocuments} full file${message.retrieval.fullDocuments === 1 ? '' : 's'}` : ''}
                                                    {message.retrieval.expandedFiles ? ` · ${message.retrieval.expandedFiles} file read${message.retrieval.expandedFiles === 1 ? '' : 's'}` : ''}
                                                </span>
                                            )}
                                        </div>
                                        {message.role === 'assistant'
                                            ? <MarkdownAnswer content={message.content} />
                                            : <p className="whitespace-pre-wrap text-sm leading-6 text-slate-100">{message.content}</p>}
                                        {message.status && <p className="mt-3 text-xs leading-5 text-amber-200/80">{message.status}</p>}
                                        {message.role === 'assistant' && <EvidenceList context={message.context} />}
                                    </div>
                                    {message.role === 'assistant' && message.timingMs && <p className="mt-1.5 px-1 text-[10px] text-slate-600">Completed in {formatSeconds(message.timingMs)}</p>}
                                </article>
                            ))}

                            {isAsking && (
                                <article className="max-w-3xl rounded-lg border border-white/[0.08] bg-white/[0.025] px-4 py-4 sm:px-5">
                                    <div className="flex items-center gap-2 text-sm text-slate-400"><LoaderCircle className="h-4 w-4 animate-spin text-emerald-300" /> Retrieving evidence and reading the relevant source passages.</div>
                                </article>
                            )}
                        </div>

                        <div className="border-t border-white/[0.07] bg-[#080d15] p-3 sm:p-4">
                            <div className="rounded-lg border border-white/[0.1] bg-white/[0.025] p-2 focus-within:border-emerald-500/35">
                                <div className="flex gap-2">
                                    <input value={ticker} onChange={event => setTicker(event.target.value.toUpperCase())} aria-label="Optional ticker context" title="Optional ticker context" placeholder="Ticker (opt.)" className="h-10 w-[104px] shrink-0 rounded-md border border-white/[0.09] bg-[#080d15] px-2.5 font-mono text-sm font-bold text-white outline-none placeholder:font-sans placeholder:font-normal focus:border-emerald-500/35 sm:w-[126px]" />
                                    <textarea
                                        value={draft}
                                        onChange={event => setDraft(event.target.value)}
                                        onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendQuestion(); } }}
                                        rows={2}
                                        aria-label="Research question"
                                        placeholder="Ask about a company, thesis, trend, or source..."
                                        className="min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 text-white outline-none placeholder:text-slate-600"
                                    />
                                    <Button type="button" tone="primary" onClick={() => void sendQuestion()} disabled={!ready || !draft.trim() || isAsking} className="h-10 min-h-10 w-10 shrink-0 px-0" aria-label="Send question">
                                        {isAsking ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                                    </Button>
                                </div>
                            </div>
                            <p className="mt-2 px-1 text-[10px] text-slate-600">Enter to send · Shift + Enter for a new line · sources are attached to every answer</p>
                        </div>
                    </section>

                    <aside className="space-y-3">
                        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-4">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2"><Library className="h-4 w-4 text-cyan-300" /><h2 className="text-[11px] font-bold uppercase tracking-[0.11em] text-slate-300">Library</h2></div>
                                <Button type="button" onClick={() => void refresh()} className="min-h-7 px-2" aria-label="Refresh library status"><RefreshCw className="h-3.5 w-3.5" /></Button>
                            </div>
                            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                                <div><dt className="text-slate-500">Sources</dt><dd className="mt-0.5 font-semibold text-white">{formatCount(counts.sources)}</dd></div>
                                <div><dt className="text-slate-500">Passages</dt><dd className="mt-0.5 font-semibold text-white">{formatCount(embeddings.total ?? counts.chunks)}</dd></div>
                                <div><dt className="text-slate-500">Semantic index</dt><dd className={cn('mt-0.5 font-semibold', allEmbedded ? 'text-emerald-300' : 'text-amber-300')}>{formatPercent(embeddings.coverage)}</dd></div>
                                <div><dt className="text-slate-500">Storage</dt><dd className="mt-0.5 font-semibold text-white">{status?.storage === 'postgres_pgvector' ? 'Supabase' : 'Local'}</dd></div>
                            </dl>
                            <div className="mt-4 grid grid-cols-2 gap-2">
                                {!drive?.connected ? <Button type="button" tone="primary" onClick={() => void connectDrive()} disabled={!ready}><Cloud className="h-3.5 w-3.5" /> Connect</Button> : <Button type="button" onClick={() => void syncDrive()} disabled={!ready}><FolderSync className="h-3.5 w-3.5" /> Sync Drive</Button>}
                                <Button type="button" tone="success" onClick={() => void embedMissing()} disabled={!ready || (embeddings.missing ?? 0) === 0}><Sparkles className="h-3.5 w-3.5" /> Embed {embeddings.missing ? formatCount(embeddings.missing) : 'Ready'}</Button>
                            </div>
                            {drive?.connectionState === 'needs_reconnect' && <p className="mt-2 text-xs leading-5 text-amber-300">{drive.connectionMessage ?? 'Google Drive authorization expired. Reconnect to sync new files.'}</p>}
                            {drive?.folderUrl && <a href={drive.folderUrl} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-slate-400 transition-colors hover:text-emerald-300">Open Drive folder <ExternalLink className="h-3.5 w-3.5" /></a>}
                            <div className="mt-4 flex items-start justify-between gap-3 border-t border-white/[0.07] pt-3">
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2"><BookOpenCheck className="h-3.5 w-3.5 text-violet-300" /><span className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-400">Reference layer</span></div>
                                    <p className="mt-1 truncate text-xs text-slate-500">{referenceSources.length ? referenceSources.map(source => sourceName(source)).join(' / ') : 'No persistent framework selected'}</p>
                                </div>
                                <Button type="button" onClick={() => void openReferencePicker()} disabled={!ready} className="min-h-7 shrink-0 px-2 text-[9px]">Manage</Button>
                            </div>
                            <div className="mt-3 flex items-start justify-between gap-3 border-t border-white/[0.07] pt-3">
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2"><FileSearch className="h-3.5 w-3.5 text-cyan-300" /><span className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-400">Full-document context</span></div>
                                    <p className="mt-1 truncate text-xs text-slate-500">{fullContextSources.length ? fullContextSources.map(source => sourceName(source)).join(' / ') : 'No whole files selected'}</p>
                                </div>
                                <Button type="button" onClick={() => void openFullContextPicker()} disabled={!ready} className="min-h-7 shrink-0 px-2 text-[9px]">Manage</Button>
                            </div>
                            <div className="mt-3 flex items-start justify-between gap-3 border-t border-white/[0.07] pt-3">
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2"><Sparkles className="h-3.5 w-3.5 text-amber-300" /><span className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-400">AI system prompt</span></div>
                                    <p className="mt-1 truncate text-xs text-slate-500">{systemPrompt ? excerpt(systemPrompt, 92) : 'Default research instructions'}</p>
                                </div>
                                <Button type="button" onClick={() => void openSystemPrompt()} disabled={!ready} className="min-h-7 shrink-0 px-2 text-[9px]">Edit</Button>
                            </div>
                        </section>

                        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-4">
                            <div className="flex items-center gap-2"><Search className="h-4 w-4 text-sky-300" /><h2 className="text-[11px] font-bold uppercase tracking-[0.11em] text-slate-300">Search sources</h2></div>
                            <div className="mt-3 flex gap-2">
                                <input value={libraryQuery} onChange={event => setLibraryQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void searchLibrary(); }} placeholder="Search your library" className="h-9 min-w-0 flex-1 rounded-md border border-white/[0.09] bg-white/[0.025] px-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-sky-500/35" />
                                <Button type="button" onClick={() => void searchLibrary()} disabled={!ready || !libraryQuery.trim() || isSearching} className="min-h-9 px-2.5" aria-label="Search library">{isSearching ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}</Button>
                            </div>
                            {librarySearch && (
                                <div className="mt-3 border-t border-white/[0.07] pt-3">
                                    <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">{librarySearch.label} · {librarySearch.results.length}</p>
                                    <div className="mt-2 space-y-2">
                                        {librarySearch.results.length ? librarySearch.results.slice(0, 4).map(result => {
                                            const link = sourceLink(result.source);
                                            return <article key={`${result.entityType}-${result.entityId}`} className="rounded-md border border-white/[0.06] bg-black/15 px-3 py-2.5"><div className="flex items-start justify-between gap-2"><p className="min-w-0 text-xs font-semibold leading-5 text-slate-200">{sourceName(result.source, result.title)}</p>{link && <a href={link} target="_blank" rel="noreferrer" className="shrink-0 text-slate-500 hover:text-sky-300"><ArrowUpRight className="h-3.5 w-3.5" /></a>}</div><p className="mt-1 text-[11px] leading-5 text-slate-500">{excerpt(result.body, 125)}</p></article>;
                                        }) : <p className="text-xs text-slate-500">No matching passages.</p>}
                                    </div>
                                </div>
                            )}
                        </section>

                        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-4">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2"><FileSearch className="h-4 w-4 text-violet-300" /><h2 className="text-[11px] font-bold uppercase tracking-[0.11em] text-slate-300">Official filing finder</h2></div>
                                <span className="rounded border border-white/[0.08] px-1.5 py-1 text-[9px] font-bold uppercase tracking-[0.08em] text-slate-500">SEC EDGAR</span>
                            </div>
                            <div className="mt-3 flex gap-2">
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
                                    <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
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
                        </section>
                    </aside>
                </div>
            </main>
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
