import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    ArrowLeft,
    Archive,
    BrainCircuit,
    CheckCircle2,
    Cloud,
    Copy,
    Database,
    ExternalLink,
    FileText,
    FolderSync,
    Layers3,
    MessageSquare,
    Plus,
    RotateCcw,
    Search,
    Send,
    ServerCog,
    ShieldAlert,
    Sparkles,
    Target,
} from 'lucide-react';
import { cn } from '../lib/utils';

type BrainSourceReference = {
    id?: number;
    title?: string;
    kind?: string;
    tags?: string[];
    sourceType?: string;
    fileName?: string;
    relativePath?: string;
    webUrl?: string;
    localPath?: string;
    driveFileId?: string;
    author?: string | null;
    sourceDate?: string | null;
    metadata?: Record<string, unknown>;
};

type SearchResult = {
    entityType: string;
    entityId: number;
    title: string;
    body: string;
    tags: string[];
    rank?: number;
    score?: number;
    ordinal?: number;
    pageStart?: number | null;
    pageEnd?: number | null;
    sourceId?: number;
    source?: BrainSourceReference;
};

type BrainCounts = {
    memories?: number;
    sources?: number;
    chunks?: number;
    ideas?: number;
    theses?: number;
    edges?: number;
    indexed?: number;
};

type EmbeddingStats = {
    total?: number;
    embedded?: number;
    missing?: number;
    coverage?: number;
    models?: { model: string; count: number }[];
};

type BrainStatus = {
    state?: string;
    database?: string;
    storage?: string;
    search?: string;
    vectorSearch?: string;
    counts?: BrainCounts;
    embeddings?: EmbeddingStats;
    capabilities?: string[];
    llm?: BrainLlmStatus;
};

type BrainLlmStatus = {
    provider?: string | null;
    configured: boolean;
    generationModel?: string;
    embeddingModel?: string;
    apiKeyEnv?: string;
};

type DriveIndexerStatus = {
    configured: boolean;
    folderId?: string | null;
    folderUrl?: string | null;
    authConfigured: boolean;
    connected: boolean;
    tokenSource?: string | null;
    supportedExtensions: string[];
    pdfAvailable: boolean;
    storageMode: string;
};

type DriveIndexResult = {
    id?: string;
    name?: string;
    relativePath: string;
    status: 'indexed' | 'skipped' | 'error';
    reason?: string;
    sourceId?: number;
    chunks?: number;
    bytes?: number;
    webViewLink?: string;
};

type DriveIndexResponse = {
    folderId: string;
    folderUrl?: string;
    summary: {
        found: number;
        indexed: number;
        skipped: number;
        errors: number;
        deferred?: number;
        limitFiles?: number;
        limitReached?: boolean;
    };
    results: DriveIndexResult[];
    counts?: BrainCounts;
};

type DriveIndexJob = {
    running: boolean;
    startedAt?: string | null;
    finishedAt?: string | null;
    folderId?: string | null;
    folderUrl?: string | null;
    summary?: DriveIndexResponse['summary'] | null;
    progress?: {
        processed?: number;
        total?: number;
        currentFile?: string | null;
        summary?: DriveIndexResponse['summary'];
    } | null;
    counts?: BrainCounts | null;
    results?: DriveIndexResult[];
    message?: string;
};

type EmbeddingBackfillJob = {
    running: boolean;
    startedAt?: string | null;
    finishedAt?: string | null;
    model?: string | null;
    requested?: number;
    embedded?: number;
    errors?: { id?: number; title?: string; error: string }[];
    message?: string;
    embeddings?: EmbeddingStats | null;
};

type BrainAnalysisResponse = {
    ticker: string;
    question: string;
    model: string;
    embeddingModel: string;
    answer: string;
    timings?: {
        totalMs?: number;
        generationMs?: number;
        semanticSearchMs?: number;
        keywordSearchMs?: number;
        memorySearchMs?: number;
        semanticError?: string;
        generationError?: string;
    };
    context?: BrainAnalysisContext;
};

type BrainConversationRole = 'user' | 'assistant';

type BrainConversationTurn = {
    role: BrainConversationRole;
    content: string;
};

type BrainThreadMessage = BrainConversationTurn & {
    id: string;
    createdAt: string;
};

type BrainDeepSource = {
    sourceId?: number;
    source?: BrainSourceReference | null;
    hitOrdinals?: number[];
    chunks?: SearchResult[];
};

type BrainAnalysisContext = {
    retrieved?: SearchResult[];
    deepSources?: BrainDeepSource[];
};

type AnswerSourceCard = {
    key: string;
    marker: string;
    title: string;
    detail?: string;
    excerpt?: string;
    score?: number;
    source?: BrainSourceReference | null;
    path?: string;
    webUrl?: string;
    tone: 'retrieved' | 'expanded';
};

type BackendState = 'checking' | 'ready' | 'offline';
type ApiErrorDetail = string | { message?: string; reason?: string; action?: string };
type ApiErrorPayload = { detail?: ApiErrorDetail };
type MarkdownBlock =
    | { type: 'heading'; level: number; content: string }
    | { type: 'paragraph'; content: string }
    | { type: 'list'; ordered: boolean; items: string[] }
    | { type: 'quote'; content: string }
    | { type: 'code'; language?: string; content: string }
    | { type: 'rule' };

const DEFAULT_BRAIN_API_URL = 'https://dashboard-eo6k.onrender.com';
const API_BASE = (
    import.meta.env.VITE_BRAIN_API_URL
    ?? import.meta.env.VITE_API_URL
    ?? DEFAULT_BRAIN_API_URL
).replace(/\/$/, '');

const brainApiUrl = (path: string) => `${API_BASE}${path}`;

const fetchWithTimeout = async (url: string, options: RequestInit = {}, timeoutMs = 12000) => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } finally {
        window.clearTimeout(timeout);
    }
};

const isAbortError = (error: unknown) =>
    error instanceof DOMException && error.name === 'AbortError';

const apiErrorMessage = (payload: ApiErrorPayload | null | undefined, fallback: string) => {
    const detail = payload?.detail;
    if (!detail) return fallback;
    if (typeof detail === 'string') return detail;
    return [detail.message, detail.reason, detail.action].filter(Boolean).join(' ');
};

const compactProviderError = (error: string | undefined) => {
    if (!error) return '';
    const normalized = error.replace(/\s+/g, ' ').trim();
    if (/http 403|forbidden/i.test(normalized)) {
        return 'Google AI rejected the request (403). The Render AI key is present but not accepted; replace it with a valid Google AI Studio key.';
    }
    if (/timed out/i.test(normalized)) {
        if (/semantic|embedding|vector/i.test(normalized)) {
            return 'Semantic embedding timed out; keyword search will still be used.';
        }
        if (/gemini|analysis|generation|answer/i.test(normalized)) {
            return 'Gemini answer timed out; retrieved sources are still shown when available.';
        }
        return 'Brain request timed out. Try again after Render and Google are stable.';
    }
    return normalized.slice(0, 220);
};

const driveJobMessage = (job: DriveIndexJob) => {
    if (job.running && job.progress) {
        const processed = job.progress.processed ?? 0;
        const total = job.progress.total ?? 0;
        const currentFile = job.progress.currentFile ? ` ${job.progress.currentFile.slice(0, 140)}` : '';
        return `Syncing Drive ${processed}/${total} file(s).${currentFile}`;
    }
    if (job.summary) {
        const summary = job.summary;
        const deferred = summary.deferred ? ` ${summary.deferred} deferred for next batch.` : '';
        return `${summary.indexed} indexed, ${summary.skipped} skipped, ${summary.errors} errors from ${summary.found} Drive file(s).${deferred}`;
    }
    return job.message ?? 'Drive sync running...';
};

const sourceReferenceDisplayName = (source?: BrainSourceReference | null, fallback = '') =>
    source?.title
    ?? source?.fileName
    ?? source?.relativePath
    ?? fallback;

const sourceDisplayName = (result: SearchResult) =>
    sourceReferenceDisplayName(result.source, result.sourceId ? `Source ${result.sourceId}` : '');

const shortExcerpt = (value?: string, maxLength = 260) => {
    const cleaned = (value ?? '').replace(/\s+/g, ' ').trim();
    if (cleaned.length <= maxLength) return cleaned;
    return `${cleaned.slice(0, maxLength).trim()}...`;
};

const chunkDetail = (item: SearchResult) => {
    const details = [];
    if (typeof item.ordinal === 'number') details.push(`chunk ${item.ordinal}`);
    if (typeof item.pageStart === 'number') {
        const pageEnd = typeof item.pageEnd === 'number' && item.pageEnd !== item.pageStart ? `-${item.pageEnd}` : '';
        details.push(`p. ${item.pageStart}${pageEnd}`);
    }
    return details.join(' · ');
};

const buildAnswerSources = (context?: BrainAnalysisContext | null): AnswerSourceCard[] => {
    if (!context) return [];

    const cards: AnswerSourceCard[] = [];
    const seenExpandedSources = new Set<string>();

    (context.retrieved ?? []).forEach((item, index) => {
        const source = item.source ?? null;
        const fallbackSource = item.sourceId ? `Source ${item.sourceId}` : item.entityType;
        const sourceName = sourceReferenceDisplayName(source, fallbackSource);
        const detail = [sourceName, chunkDetail(item)].filter(Boolean).join(' · ');
        cards.push({
            key: `retrieved-${item.entityType}-${item.entityId}-${index}`,
            marker: `[${index + 1}]`,
            title: item.title || sourceName || `Evidence ${index + 1}`,
            detail,
            excerpt: shortExcerpt(item.body),
            score: item.score ?? item.rank,
            source,
            path: source?.webUrl ? undefined : source?.relativePath,
            webUrl: source?.webUrl,
            tone: 'retrieved',
        });
    });

    (context.deepSources ?? []).forEach((item, index) => {
        const source = item.source ?? null;
        const sourceKey = String(item.sourceId ?? source?.id ?? index);
        if (seenExpandedSources.has(sourceKey)) return;
        seenExpandedSources.add(sourceKey);

        const chunks = item.chunks ?? [];
        const hitOrdinals = item.hitOrdinals?.length ? `semantic hits ${item.hitOrdinals.join(', ')}` : '';
        const chunkCount = chunks.length ? `${chunks.length} expanded chunks` : '';
        const title = sourceReferenceDisplayName(source, item.sourceId ? `Source ${item.sourceId}` : `Expanded file ${index + 1}`);
        cards.push({
            key: `expanded-${sourceKey}`,
            marker: `File ${index + 1}`,
            title,
            detail: [hitOrdinals, chunkCount].filter(Boolean).join(' · '),
            excerpt: shortExcerpt(chunks.find(chunk => chunk.body)?.body),
            source,
            path: source?.webUrl ? undefined : source?.relativePath,
            webUrl: source?.webUrl,
            tone: 'expanded',
        });
    });

    return cards.slice(0, 10);
};

const sourceToneClass: Record<AnswerSourceCard['tone'], string> = {
    retrieved: 'border-sky-500/20 bg-sky-500/10 text-sky-200',
    expanded: 'border-violet-500/20 bg-violet-500/10 text-violet-200',
};

const inlineMarkdownPattern = /(\[[^\]]+\]\((https?:\/\/[^)\s]+)\)|`([^`]+)`|\*\*([^*]+)\*\*|\*([^*]+)\*)/g;

const renderInlineMarkdown = (text: string, keyPrefix: string): React.ReactNode[] => {
    const nodes: React.ReactNode[] = [];
    let lastIndex = 0;

    for (const match of text.matchAll(inlineMarkdownPattern)) {
        const index = match.index ?? 0;
        if (index > lastIndex) {
            nodes.push(text.slice(lastIndex, index));
        }

        const [raw, linkRaw, linkUrl, codeRaw, boldRaw, italicRaw] = match;
        const key = `${keyPrefix}-${index}`;

        if (linkRaw && linkUrl) {
            const label = linkRaw.slice(1, linkRaw.indexOf(']('));
            nodes.push(
                <a
                    key={key}
                    href={linkUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="font-semibold text-sky-300 underline decoration-sky-400/35 underline-offset-4 transition-colors hover:text-sky-200"
                >
                    {label}
                </a>
            );
        } else if (codeRaw) {
            nodes.push(
                <code key={key} className="rounded border border-white/10 bg-white/[0.06] px-1.5 py-0.5 font-mono text-[0.92em] text-emerald-200">
                    {codeRaw}
                </code>
            );
        } else if (boldRaw) {
            nodes.push(
                <strong key={key} className="font-black text-white">
                    {boldRaw}
                </strong>
            );
        } else if (italicRaw) {
            nodes.push(
                <em key={key} className="text-slate-200">
                    {italicRaw}
                </em>
            );
        } else {
            nodes.push(raw);
        }

        lastIndex = index + raw.length;
    }

    if (lastIndex < text.length) {
        nodes.push(text.slice(lastIndex));
    }

    return nodes.length ? nodes : [text];
};

const parseMarkdownBlocks = (content: string): MarkdownBlock[] => {
    const lines = content.replace(/\r\n/g, '\n').split('\n');
    const blocks: MarkdownBlock[] = [];
    let index = 0;

    while (index < lines.length) {
        const line = lines[index];
        const trimmed = line.trim();

        if (!trimmed) {
            index += 1;
            continue;
        }

        const fence = trimmed.match(/^```([\w-]*)\s*$/);
        if (fence) {
            const language = fence[1] || undefined;
            const codeLines: string[] = [];
            index += 1;
            while (index < lines.length && !lines[index].trim().startsWith('```')) {
                codeLines.push(lines[index]);
                index += 1;
            }
            if (index < lines.length) index += 1;
            blocks.push({ type: 'code', language, content: codeLines.join('\n') });
            continue;
        }

        const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
            blocks.push({ type: 'heading', level: heading[1].length, content: heading[2].trim() });
            index += 1;
            continue;
        }

        if (/^[-*_]{3,}$/.test(trimmed)) {
            blocks.push({ type: 'rule' });
            index += 1;
            continue;
        }

        if (trimmed.startsWith('>')) {
            const quoteLines: string[] = [];
            while (index < lines.length && lines[index].trim().startsWith('>')) {
                quoteLines.push(lines[index].trim().replace(/^>\s?/, ''));
                index += 1;
            }
            blocks.push({ type: 'quote', content: quoteLines.join(' ') });
            continue;
        }

        const bulletMatch = trimmed.match(/^([-*])\s+(.+)$/);
        const orderedMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);
        if (bulletMatch || orderedMatch) {
            const ordered = Boolean(orderedMatch);
            const items: string[] = [];
            while (index < lines.length) {
                const itemLine = lines[index].trim();
                const nextBullet = itemLine.match(/^[-*]\s+(.+)$/);
                const nextOrdered = itemLine.match(/^\d+[.)]\s+(.+)$/);
                if (ordered ? !nextOrdered : !nextBullet) break;
                items.push((ordered ? nextOrdered?.[1] : nextBullet?.[1])?.trim() ?? '');
                index += 1;
            }
            blocks.push({ type: 'list', ordered, items });
            continue;
        }

        const paragraphLines = [trimmed];
        index += 1;
        while (index < lines.length) {
            const next = lines[index].trim();
            if (
                !next
                || /^```/.test(next)
                || /^(#{1,4})\s+/.test(next)
                || /^[-*_]{3,}$/.test(next)
                || /^>/.test(next)
                || /^[-*]\s+/.test(next)
                || /^\d+[.)]\s+/.test(next)
            ) {
                break;
            }
            paragraphLines.push(next);
            index += 1;
        }
        blocks.push({ type: 'paragraph', content: paragraphLines.join(' ') });
    }

    return blocks;
};

const MarkdownAnswer: React.FC<{ content: string }> = ({ content }) => {
    const blocks = useMemo(() => parseMarkdownBlocks(content), [content]);

    if (!blocks.length) {
        return <p className="text-sm leading-6 text-slate-500">No answer text returned.</p>;
    }

    return (
        <div className="space-y-3 break-words text-sm leading-6 text-slate-100">
            {blocks.map((block, index) => {
                const key = `md-${index}`;
                if (block.type === 'heading') {
                    const headingClass = block.level <= 2
                        ? 'mt-1 text-base font-black leading-6 text-white'
                        : 'mt-1 text-sm font-black uppercase tracking-[0.08em] text-slate-200';
                    return (
                        <h4 key={key} className={headingClass}>
                            {renderInlineMarkdown(block.content, key)}
                        </h4>
                    );
                }
                if (block.type === 'paragraph') {
                    return (
                        <p key={key} className="text-sm leading-6 text-slate-200">
                            {renderInlineMarkdown(block.content, key)}
                        </p>
                    );
                }
                if (block.type === 'list') {
                    const ListTag = block.ordered ? 'ol' : 'ul';
                    return (
                        <ListTag
                            key={key}
                            className={cn(
                                'space-y-2 pl-5 text-sm leading-6 text-slate-200',
                                block.ordered ? 'list-decimal' : 'list-disc'
                            )}
                        >
                            {block.items.map((item, itemIndex) => (
                                <li key={`${key}-${itemIndex}`} className="pl-1 marker:text-sky-300/80">
                                    {renderInlineMarkdown(item, `${key}-${itemIndex}`)}
                                </li>
                            ))}
                        </ListTag>
                    );
                }
                if (block.type === 'quote') {
                    return (
                        <blockquote key={key} className="rounded-md border-l-2 border-sky-400/50 bg-sky-500/10 px-3 py-2 text-sm leading-6 text-sky-100">
                            {renderInlineMarkdown(block.content, key)}
                        </blockquote>
                    );
                }
                if (block.type === 'code') {
                    return (
                        <pre key={key} className="overflow-auto rounded-md border border-white/10 bg-black/35 p-3 text-xs leading-5 text-emerald-100">
                            {block.language && (
                                <span className="mb-2 block text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-400/70">
                                    {block.language}
                                </span>
                            )}
                            <code>{block.content}</code>
                        </pre>
                    );
                }
                return <hr key={key} className="border-white/[0.08]" />;
            })}
        </div>
    );
};

const createThreadMessage = (role: BrainConversationRole, content: string): BrainThreadMessage => ({
    role,
    content,
    id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
});

const threadForApi = (messages: BrainThreadMessage[]): BrainConversationTurn[] =>
    messages
        .filter(message => message.content.trim())
        .slice(-10)
        .map(({ role, content }) => ({ role, content }));

const formatTags = (value: string) =>
    value
        .split(',')
        .map(tag => tag.trim())
        .filter(Boolean)
        .slice(0, 6);

const formatStorage = (storage?: string) => {
    if (storage === 'postgres_pgvector') return 'Supabase pgvector';
    if (storage === 'sqlite') return 'SQLite';
    return 'Not connected';
};

const formatModelLabel = (model?: string) => {
    if (!model) return 'Gemini';
    return model
        .replace(/^gemini-/i, 'Gemini ')
        .replace(/-/g, ' ')
        .replace(/\bflash lite\b/i, 'Flash Lite');
};

const formatEmbeddingCoverage = (stats?: EmbeddingStats | null) => {
    const total = stats?.total ?? 0;
    const embedded = stats?.embedded ?? 0;
    if (!total) return '0 chunks embedded';
    return `${embedded}/${total} chunks embedded`;
};

const formatEmbeddingPercent = (stats?: EmbeddingStats | null) => {
    const total = stats?.total ?? 0;
    const embedded = stats?.embedded ?? 0;
    if (!total) return '0%';
    return `${Math.round((embedded / total) * 100)}%`;
};

const formatSearchDetail = (status: BrainStatus | null, stats?: EmbeddingStats | null) => {
    if ((stats?.missing ?? 0) > 0) return formatEmbeddingCoverage(stats);
    if (status?.storage === 'postgres_pgvector') return 'Semantic search ready';
    if (status?.vectorSearch) return 'Semantic search after embeddings';
    if (status?.search) return 'Keyword search ready';
    return 'No search index yet';
};

const formatDriveFolder = (status: DriveIndexerStatus | null) => {
    if (!status?.folderId) return 'No Drive folder selected yet';
    return status.folderUrl ? 'Google Drive folder linked' : 'Drive folder ID saved';
};

const resultTone = (status: 'indexed' | 'skipped' | 'error') => {
    if (status === 'indexed') return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300';
    if (status === 'error') return 'border-rose-500/25 bg-rose-500/10 text-rose-300';
    return 'border-white/10 bg-white/[0.04] text-gray-400';
};

export const InvestmentBrain: React.FC = () => {
    const [backendState, setBackendState] = useState<BackendState>('checking');
    const [brainStatus, setBrainStatus] = useState<BrainStatus | null>(null);
    const [searchQuery, setSearchQuery] = useState('pricing power AI infrastructure');
    const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
    const [searchMessage, setSearchMessage] = useState('');
    const [isSearching, setIsSearching] = useState(false);
    const [backendCounts, setBackendCounts] = useState<BrainCounts | null>(null);
    const [embeddingStats, setEmbeddingStats] = useState<EmbeddingStats | null>(null);
    const [sourceTitle, setSourceTitle] = useState('');
    const [sourceBody, setSourceBody] = useState('');
    const [sourceTags, setSourceTags] = useState('');
    const [ingestMessage, setIngestMessage] = useState('');
    const [isIngesting, setIsIngesting] = useState(false);
    const [driveStatus, setDriveStatus] = useState<DriveIndexerStatus | null>(null);
    const [isDriveSyncing, setIsDriveSyncing] = useState(false);
    const [driveMessage, setDriveMessage] = useState('');
    const [driveResults, setDriveResults] = useState<DriveIndexResult[]>([]);
    const [llmStatus, setLlmStatus] = useState<BrainLlmStatus | null>(null);
    const [isEmbedding, setIsEmbedding] = useState(false);
    const [embeddingMessage, setEmbeddingMessage] = useState('');
    const [analysisTicker, setAnalysisTicker] = useState('META');
    const [analysisQuestion, setAnalysisQuestion] = useState('What does my brain say about the moat, risks, valuation lens, and what would change my mind?');
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [analysisMessage, setAnalysisMessage] = useState('');
    const [analysisAnswer, setAnalysisAnswer] = useState('');
    const [analysisContext, setAnalysisContext] = useState<BrainAnalysisContext | null>(null);
    const [analysisThread, setAnalysisThread] = useState<BrainThreadMessage[]>([]);
    const [followUpQuestion, setFollowUpQuestion] = useState('');
    const analysisOutputRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        if (!isAnalyzing && !analysisAnswer && analysisThread.length === 0) return;
        window.setTimeout(() => {
            analysisOutputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 80);
    }, [isAnalyzing, analysisAnswer, analysisThread.length]);

    useEffect(() => {
        let cancelled = false;

        const loadBackend = async () => {
            try {
                const statusResponse = await fetch(brainApiUrl('/api/brain/status'));
                if (!statusResponse.ok) throw new Error('Brain status unavailable');
                const status = await statusResponse.json() as BrainStatus;

                let nextDriveStatus: DriveIndexerStatus | null = null;

                try {
                    const driveResponse = await fetch(brainApiUrl('/api/brain/index/drive/status'));
                    if (driveResponse.ok) {
                        nextDriveStatus = await driveResponse.json() as DriveIndexerStatus;
                    }
                } catch {
                    nextDriveStatus = null;
                }

                if (!cancelled) {
                    setBackendState('ready');
                    setBrainStatus(status);
                    setBackendCounts(status.counts ?? null);
                    setEmbeddingStats(status.embeddings ?? null);
                    setLlmStatus(status.llm ?? null);
                    setDriveStatus(nextDriveStatus);
                }
            } catch {
                if (!cancelled) {
                    setBackendState('offline');
                }
            }
        };

        loadBackend();

        return () => {
            cancelled = true;
        };
    }, []);

    const answerSources = useMemo(() => buildAnswerSources(analysisContext), [analysisContext]);

    const runBackendSearch = async () => {
        const cleanedQuery = searchQuery.trim();
        if (!cleanedQuery) return;

        setIsSearching(true);
        setSearchMessage('Searching Supabase embeddings...');
        setSearchResults([]);
        try {
            const params = new URLSearchParams({ q: cleanedQuery, limit: '12' });
            let semanticTimedOut = false;
            let semanticUnavailable = false;
            let semanticUnavailableReason = '';

            try {
                const semanticResponse = await fetchWithTimeout(
                    brainApiUrl(`/api/brain/search/semantic?${params.toString()}`),
                    {},
                    14000
                );
                if (semanticResponse.ok) {
                    const semanticPayload = await semanticResponse.json() as { results?: SearchResult[]; timings?: { totalMs?: number } };
                    const semanticResults = Array.isArray(semanticPayload.results) ? semanticPayload.results : [];
                    if (semanticResults.length > 0) {
                        const totalSeconds = typeof semanticPayload.timings?.totalMs === 'number'
                            ? ` in ${(semanticPayload.timings.totalMs / 1000).toFixed(1)}s`
                            : '';
                        setSearchResults(semanticResults);
                        setSearchMessage(`Top ${semanticResults.length} semantic match${semanticResults.length === 1 ? '' : 'es'}${totalSeconds}`);
                        return;
                    }
                } else {
                    semanticUnavailable = true;
                    const payload = await semanticResponse.json().catch(() => null) as ApiErrorPayload | null;
                    semanticUnavailableReason = apiErrorMessage(payload, 'Semantic search is not available');
                }
            } catch (error) {
                semanticTimedOut = isAbortError(error);
                semanticUnavailable = !semanticTimedOut;
                semanticUnavailableReason = error instanceof Error ? error.message : '';
            }

            setSearchMessage(semanticTimedOut
                ? 'Semantic search timed out; checking keyword index...'
                : semanticUnavailable
                    ? `${compactProviderError(semanticUnavailableReason) || 'Semantic unavailable'}; checking keyword index...`
                    : 'No vector hits yet; checking keyword index...');

            let keywordResponse: Response;
            try {
                keywordResponse = await fetchWithTimeout(
                    brainApiUrl(`/api/brain/search?${params.toString()}`),
                    {},
                    12000
                );
            } catch (error) {
                if (isAbortError(error)) {
                    throw new Error('Brain backend did not respond. Render may still be redeploying or Supabase may be slow.');
                }
                throw error;
            }

            if (!keywordResponse.ok) {
                const payload = await keywordResponse.json().catch(() => null) as { detail?: string } | null;
                throw new Error(payload?.detail ?? 'Search failed');
            }

            const payload = await keywordResponse.json() as { results?: SearchResult[]; timings?: { totalMs?: number } };
            const results = Array.isArray(payload.results) ? payload.results : [];
            const totalSeconds = typeof payload.timings?.totalMs === 'number'
                ? ` in ${(payload.timings.totalMs / 1000).toFixed(1)}s`
                : '';
            const prefix = semanticTimedOut
                ? 'Semantic timed out; '
                : semanticUnavailable
                    ? `${compactProviderError(semanticUnavailableReason) || 'Semantic unavailable'}; `
                    : (embeddingStats?.missing ?? 0) > 0
                        ? `Only ${formatEmbeddingCoverage(embeddingStats)}; `
                        : 'No vector hits yet; ';
            setSearchResults(results);
            setSearchMessage(results.length
                ? `${prefix}top ${results.length} keyword match${results.length === 1 ? '' : 'es'}${totalSeconds}`
                : `${prefix}no keyword matches${totalSeconds}. Sync Drive, then Embed Missing if this library should contain it.`);
        } catch (error) {
            setSearchResults([]);
            setSearchMessage(error instanceof Error ? error.message : 'Search is unavailable');
        } finally {
            setIsSearching(false);
        }
    };

    const ingestSourceText = async () => {
        const cleanedTitle = sourceTitle.trim();
        const cleanedBody = sourceBody.trim();
        if (!cleanedTitle || !cleanedBody || backendState !== 'ready') return;

        setIsIngesting(true);
        setIngestMessage('');
        try {
            const response = await fetch(brainApiUrl('/api/brain/ingest/text'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    kind: 'note',
                    title: cleanedTitle,
                    body: cleanedBody,
                    tags: formatTags(sourceTags),
                    chunkWords: 450,
                    overlapWords: 60,
                    metadata: {
                        origin: 'investment-brain-ui',
                        rawStorage: 'inline-text',
                    },
                }),
            });
            if (!response.ok) throw new Error('Ingestion failed');

            const payload = await response.json() as { chunks?: unknown[]; counts?: BrainCounts };
            const chunkCount = Array.isArray(payload.chunks) ? payload.chunks.length : 0;
            setBackendCounts(payload.counts ?? null);
            setIngestMessage(`Indexed ${chunkCount} chunk${chunkCount === 1 ? '' : 's'}.`);
            setSearchQuery(cleanedTitle);
        } catch {
            setIngestMessage('Ingestion is unavailable');
        } finally {
            setIsIngesting(false);
        }
    };

    const connectGoogleDrive = async () => {
        if (backendState !== 'ready') return;

        setDriveMessage('');
        try {
            const response = await fetch(brainApiUrl('/api/brain/drive/auth-url'));
            if (!response.ok) {
                const payload = await response.json().catch(() => null) as { detail?: string } | null;
                throw new Error(payload?.detail ?? 'Google Drive auth is not configured');
            }

            const payload = await response.json() as { url?: string };
            if (!payload.url) throw new Error('Google Drive auth URL is missing');
            window.open(payload.url, '_blank', 'noopener,noreferrer');
            setDriveMessage('Permission tab opened. Approve access, then refresh this page.');
        } catch (error) {
            setDriveMessage(error instanceof Error ? error.message : 'Could not start Google Drive connection');
        }
    };

    const runDriveIndex = async () => {
        if (backendState !== 'ready') return;

        setIsDriveSyncing(true);
        setDriveMessage('');
        setDriveResults([]);
        try {
            const startResponse = await fetchWithTimeout(
                brainApiUrl('/api/brain/index/drive/start'),
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        limitFiles: 2000,
                        maxBytes: 10 * 1024 * 1024,
                        changedFilesLimit: 10,
                        force: false,
                    }),
                },
                12000
            );
            if (!startResponse.ok) {
                const payload = await startResponse.json().catch(() => null) as ApiErrorPayload | null;
                throw new Error(apiErrorMessage(payload, 'Google Drive sync failed'));
            }

            let latestJob = await startResponse.json() as DriveIndexJob;
            for (let poll = 1; poll <= 240; poll += 1) {
                setDriveMessage(driveJobMessage(latestJob));
                if (latestJob.counts) setBackendCounts(latestJob.counts);
                if (latestJob.results) setDriveResults(latestJob.results);
                if (!latestJob.running && poll > 1) break;

                await new Promise(resolve => window.setTimeout(resolve, 3000));
                const statusResponse = await fetchWithTimeout(
                    brainApiUrl('/api/brain/index/drive/job/status'),
                    {},
                    12000
                );
                if (!statusResponse.ok) break;
                latestJob = await statusResponse.json() as DriveIndexJob;
            }

            if (latestJob.counts) setBackendCounts(latestJob.counts);
            if (latestJob.results) setDriveResults(latestJob.results);
            setDriveMessage(driveJobMessage(latestJob));

            const statusResponse = await fetch(brainApiUrl('/api/brain/index/drive/status'));
            if (statusResponse.ok) {
                setDriveStatus(await statusResponse.json() as DriveIndexerStatus);
            }
        } catch (error) {
            setDriveMessage(error instanceof Error ? error.message : 'Google Drive sync failed');
        } finally {
            setIsDriveSyncing(false);
        }
    };

    const backfillEmbeddings = async () => {
        if (backendState !== 'ready') return;

        setIsEmbedding(true);
        setEmbeddingMessage('');
        try {
            const startResponse = await fetchWithTimeout(
                brainApiUrl('/api/brain/embeddings/backfill/start'),
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ batchSize: 5, maxChunks: 500, force: false }),
                },
                12000
            );
            if (!startResponse.ok) {
                const payload = await startResponse.json().catch(() => null) as { detail?: string } | null;
                throw new Error(payload?.detail ?? 'Embedding job failed to start');
            }

            let latestJob = await startResponse.json() as EmbeddingBackfillJob;
            for (let poll = 1; poll <= 240; poll += 1) {
                if (latestJob.embeddings) setEmbeddingStats(latestJob.embeddings);
                const remaining = latestJob.embeddings?.missing;
                setEmbeddingMessage(`${latestJob.message ?? 'Embedding in background'}${typeof remaining === 'number' ? ` ${remaining} left.` : ''}`);
                if (!latestJob.running && poll > 1) break;

                await new Promise(resolve => window.setTimeout(resolve, 3000));
                const statusResponse = await fetchWithTimeout(
                    brainApiUrl('/api/brain/embeddings/backfill/status'),
                    {},
                    12000
                );
                if (!statusResponse.ok) break;
                latestJob = await statusResponse.json() as EmbeddingBackfillJob;
            }

            if (latestJob.embeddings) setEmbeddingStats(latestJob.embeddings);
            const statusResponse = await fetchWithTimeout(brainApiUrl('/api/brain/status'), {}, 12000);
            if (statusResponse.ok) {
                const status = await statusResponse.json() as BrainStatus;
                setBrainStatus(status);
                setBackendCounts(status.counts ?? null);
                setEmbeddingStats(status.embeddings ?? latestJob.embeddings ?? null);
            }
            const errors = latestJob.errors?.length ?? 0;
            const coverage = latestJob.embeddings ? ` ${formatEmbeddingCoverage(latestJob.embeddings)}.` : '';
            const firstError = compactProviderError(latestJob.errors?.[0]?.error);
            setEmbeddingMessage(`${latestJob.embedded ?? 0}/${latestJob.requested ?? 0} embedded in background.${coverage}${errors ? ` ${firstError || `${errors} recent error(s).`}` : ''}`);
        } catch (error) {
            setEmbeddingMessage(isAbortError(error)
                ? 'Embedding status timed out. Press Embed Missing again; the background job may still be running.'
                : error instanceof Error ? error.message : 'Embedding failed');
        } finally {
            setIsEmbedding(false);
        }
    };

    const runCompanyAnalysis = async (mode: 'new' | 'follow-up' = 'new') => {
        const ticker = analysisTicker.trim();
        if (!ticker || backendState !== 'ready') return;

        const question = mode === 'follow-up' ? followUpQuestion.trim() : analysisQuestion.trim();
        if (!question) return;

        const priorThread = mode === 'follow-up' ? analysisThread : [];
        const userMessage = createThreadMessage('user', question);
        const nextThread = [...priorThread, userMessage];

        setIsAnalyzing(true);
        setAnalysisMessage(mode === 'follow-up'
            ? 'Retrieving fresh context for the follow-up...'
            : 'Retrieving your brain context, then asking Gemini...');
        setAnalysisAnswer('');
        if (mode === 'new') {
            setAnalysisContext(null);
        }
        setAnalysisThread(nextThread);
        try {
            const response = await fetchWithTimeout(
                brainApiUrl('/api/brain/analyze-company'),
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        ticker,
                        question,
                        limit: 5,
                        useSemantic: true,
                        conversation: threadForApi(priorThread),
                    }),
                },
                65000
            );
            if (!response.ok) {
                const payload = await response.json().catch(() => null) as ApiErrorPayload | null;
                throw new Error(compactProviderError(apiErrorMessage(payload, 'Analysis failed')));
            }

            const payload = await response.json() as BrainAnalysisResponse;
            setAnalysisAnswer(payload.answer);
            setAnalysisContext(payload.context ?? null);
            setAnalysisThread([...nextThread, createThreadMessage('assistant', payload.answer)]);
            if (mode === 'follow-up') setFollowUpQuestion('');
            const totalSeconds = typeof payload.timings?.totalMs === 'number'
                ? ` in ${(payload.timings.totalMs / 1000).toFixed(1)}s`
                : '';
            const generationSeconds = typeof payload.timings?.generationMs === 'number'
                ? `, Gemini ${(payload.timings.generationMs / 1000).toFixed(1)}s`
                : '';
            const semanticFallback = payload.timings?.semanticError ? 'keyword fallback; ' : '';
            const generationFallback = payload.timings?.generationError
                ? `sources retrieved; ${compactProviderError(payload.timings.generationError).toLowerCase()}`
                : '';
            setAnalysisMessage(generationFallback
                ? generationFallback
                : `${semanticFallback}${payload.model} with ${payload.embeddingModel}${totalSeconds}${generationSeconds}`);
        } catch (error) {
            const message = isAbortError(error)
                ? 'Ask Brain timed out. Try again after Render finishes waking up, or narrow the question.'
                : error instanceof Error ? error.message : 'Analysis failed';
            setAnalysisMessage(message);
            setAnalysisThread([...nextThread, createThreadMessage('assistant', message)]);
        } finally {
            setIsAnalyzing(false);
        }
    };

    const backendReady = backendState === 'ready';
    const storageLabel = formatStorage(brainStatus?.storage);
    const counts = backendCounts ?? {};
    const hasAssistantAnswer = analysisThread.some(message => message.role === 'assistant');
    const driveConnected = Boolean(driveStatus?.connected);
    const driveConfigured = Boolean(driveStatus?.configured);
    const driveAuthReady = Boolean(driveStatus?.authConfigured);
    const totalChunks = embeddingStats?.total ?? counts.chunks ?? 0;
    const embeddedChunks = embeddingStats?.embedded ?? 0;
    const missingChunks = embeddingStats?.missing ?? Math.max(0, totalChunks - embeddedChunks);
    const embeddingPercent = formatEmbeddingPercent(embeddingStats);
    const libraryReady = totalChunks > 0 && missingChunks <= 0;
    const copySourcePath = async (path: string) => {
        try {
            await navigator.clipboard.writeText(path);
            setSearchMessage('Local file path copied');
        } catch {
            setSearchMessage('Could not copy path');
        }
    };
    const resetBrainThread = () => {
        setAnalysisThread([]);
        setAnalysisAnswer('');
        setAnalysisContext(null);
        setAnalysisMessage('');
        setFollowUpQuestion('');
    };
    const nextAction = !backendReady
        ? {
            title: 'Backend offline',
            detail: 'Reconnect Render before indexing or analyzing.',
            label: 'Waiting',
            Icon: ShieldAlert,
            onClick: undefined,
            disabled: true,
        }
        : driveConfigured && driveAuthReady && !driveConnected
            ? {
                title: 'Connect Google Drive',
                detail: 'Authorize Drive once to sync the research library.',
                label: 'Connect Drive',
                Icon: ExternalLink,
                onClick: connectGoogleDrive,
                disabled: false,
            }
            : driveConnected && (counts.chunks ?? 0) === 0
                ? {
                    title: 'Sync your Drive library',
                    detail: 'Index supported PDFs, docs, notes, and text files.',
                    label: isDriveSyncing ? 'Syncing' : 'Sync Drive',
                    Icon: FolderSync,
                    onClick: runDriveIndex,
                    disabled: isDriveSyncing,
                }
                : (counts.chunks ?? 0) > 0 && missingChunks > 0
                    ? {
                        title: `${missingChunks.toLocaleString()} chunks need embeddings`,
                        detail: `${formatEmbeddingCoverage(embeddingStats)}. Finish the semantic layer before relying on retrieval.`,
                        label: isEmbedding ? 'Embedding' : 'Embed Missing',
                        Icon: Sparkles,
                        onClick: backfillEmbeddings,
                        disabled: isEmbedding,
                    }
                    : {
                        title: libraryReady ? 'Research library ready' : 'Start with one source',
                        detail: libraryReady
                            ? `${(counts.sources ?? 0).toLocaleString()} sources and ${totalChunks.toLocaleString()} embedded chunks are queryable.`
                            : 'Paste a note or connect Drive to seed the library.',
                        label: libraryReady ? 'Ready' : 'Waiting',
                        Icon: CheckCircle2,
                        onClick: undefined,
                        disabled: true,
                    };

    const statusCards = [
        {
            label: 'Storage',
            value: brainStatus?.storage === 'postgres_pgvector' ? 'Supabase' : storageLabel,
            detail: brainStatus?.storage === 'postgres_pgvector' ? 'vector store online' : formatSearchDetail(brainStatus, embeddingStats),
            Icon: Database,
            className: brainStatus?.storage === 'postgres_pgvector' ? 'text-emerald-300' : 'text-amber-300',
        },
        {
            label: 'AI',
            value: llmStatus?.configured ? formatModelLabel(llmStatus.generationModel) : 'Missing key',
            detail: llmStatus?.configured ? llmStatus.embeddingModel ?? 'embedding model' : 'add Google AI key',
            Icon: Sparkles,
            className: llmStatus?.configured ? 'text-violet-300' : 'text-amber-300',
        },
        {
            label: 'Drive',
            value: driveConnected ? 'Connected' : driveAuthReady ? 'Needs auth' : 'Not connected',
            detail: driveStatus?.folderId ? 'folder linked' : 'folder missing',
            Icon: Cloud,
            className: driveConnected ? 'text-emerald-300' : driveAuthReady ? 'text-amber-300' : 'text-gray-400',
        },
        {
            label: 'Indexed',
            value: `${counts.sources ?? 0} sources`,
            detail: `${embeddingPercent} embedded`,
            Icon: Layers3,
            className: 'text-sky-300',
            progress: totalChunks ? Math.min(100, Math.round((embeddedChunks / totalChunks) * 100)) : 0,
        },
    ];

    const latestIndexResults = driveResults;

    return (
        <div className="min-h-screen bg-[#06080d] text-foreground">
            <div className="animated-top-bar h-[2px] w-full" />

            <main className="mx-auto max-w-[1560px] px-4 py-4 sm:px-6 lg:px-8">
                <header className="flex flex-col gap-4 border-b border-white/[0.07] pb-4 lg:flex-row lg:items-end lg:justify-between">
                    <div className="min-w-0">
                        <a
                            href="/"
                            className="inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.12em] text-slate-500 transition-colors hover:text-slate-300"
                        >
                            <ArrowLeft className="h-3.5 w-3.5" />
                            Dashboard
                        </a>
                        <div className="mt-3 flex items-center gap-3">
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-emerald-400/20 bg-emerald-400/10">
                                <BrainCircuit className="h-5 w-5 text-emerald-300" />
                            </div>
                            <div className="min-w-0">
                                <h1 className="text-2xl font-black tracking-normal text-white md:text-3xl">
                                    Investment Brain
                                </h1>
                                <p className="mt-1 max-w-3xl text-sm leading-5 text-slate-400">
                                    Semantic equity research cockpit for source retrieval, file-backed questions, and company work.
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                        <span className={cn(
                            'inline-flex min-h-[32px] items-center rounded-md border px-3 text-[10px] font-bold uppercase tracking-[0.1em]',
                            backendReady ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                        )}>
                            {backendReady ? 'Backend ready' : backendState === 'checking' ? 'Checking' : 'Offline'}
                        </span>
                        <span className="inline-flex min-h-[32px] items-center rounded-md border border-white/10 bg-white/[0.035] px-3 text-[10px] font-bold uppercase tracking-[0.1em] text-slate-300">
                            {storageLabel}
                        </span>
                    </div>
                </header>

                <section className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-4">
                    {statusCards.map(item => {
                        const Icon = item.Icon;
                        return (
                            <div key={item.label} className="min-w-0 rounded-lg border border-white/[0.08] bg-[#0b1019]/90 px-3 py-3">
                                <div className="flex items-center justify-between gap-2">
                                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">{item.label}</span>
                                    <Icon className={cn('h-4 w-4', item.className)} />
                                </div>
                                <p className="mt-2 break-words text-sm font-black leading-5 text-white sm:text-base">{item.value}</p>
                                <p className="mt-0.5 truncate text-[11px] text-slate-500">{item.detail}</p>
                                {'progress' in item && (
                                    <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
                                        <div
                                            className="h-full rounded-full bg-cyan-300/80"
                                            style={{ width: `${item.progress}%` }}
                                        />
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </section>

                <section className="mt-3 rounded-lg border border-white/[0.08] bg-[#0a1020]/95 p-3 sm:p-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                        <div className="flex min-w-0 items-start gap-3">
                            <div className={cn(
                                'flex h-9 w-9 shrink-0 items-center justify-center rounded-md border',
                                libraryReady ? 'border-emerald-500/20 bg-emerald-500/10' : 'border-cyan-500/20 bg-cyan-500/10'
                            )}>
                                <nextAction.Icon className={cn('h-[18px] w-[18px]', libraryReady ? 'text-emerald-300' : 'text-cyan-300')} />
                            </div>
                            <div className="min-w-0">
                                <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">Readiness</p>
                                <h2 className="mt-0.5 text-lg font-black text-white">{nextAction.title}</h2>
                                <p className="mt-0.5 text-sm leading-5 text-slate-400">{nextAction.detail}</p>
                                {(driveMessage || embeddingMessage) && (
                                    <p className="mt-2 text-xs font-semibold text-emerald-100/80">
                                        {driveMessage || embeddingMessage}
                                    </p>
                                )}
                            </div>
                        </div>
                        <div className="flex flex-col gap-2 sm:flex-row">
                            {driveStatus?.folderUrl && (
                                <a
                                    href={driveStatus.folderUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="inline-flex min-h-[38px] items-center justify-center gap-2 rounded-md border border-white/10 bg-white/[0.035] px-4 text-xs font-bold uppercase tracking-[0.1em] text-slate-300 transition-colors hover:bg-white/[0.07]"
                                >
                                    <ExternalLink className="h-4 w-4" />
                                    Drive
                                </a>
                            )}
                            <button
                                type="button"
                                onClick={nextAction.onClick}
                                disabled={nextAction.disabled}
                                className={cn(
                                    'inline-flex min-h-[38px] items-center justify-center gap-2 rounded-md border px-4 text-xs font-bold uppercase tracking-[0.1em] transition-colors',
                                    nextAction.disabled
                                        ? 'cursor-not-allowed border-white/10 bg-white/[0.025] text-slate-600'
                                        : 'border-emerald-500/30 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/20'
                                )}
                            >
                                <nextAction.Icon className="h-4 w-4" />
                                {nextAction.label}
                            </button>
                        </div>
                    </div>
                </section>

                <section className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.18fr)_380px]">
                    <div className="space-y-4">
                        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-3 sm:p-4">
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                                <div className="flex items-center gap-2">
                                    <Target className="h-4 w-4 text-rose-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">Company Query</h2>
                                </div>
                                <span className={cn(
                                    'inline-flex w-fit rounded-md border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.1em]',
                                    llmStatus?.configured ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                                )}>
                                    {llmStatus?.configured ? llmStatus.generationModel ?? 'Gemini ready' : 'API key missing'}
                                </span>
                            </div>

                            <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-[96px_minmax(0,1fr)_132px]">
                                <input
                                    value={analysisTicker}
                                    onChange={event => setAnalysisTicker(event.target.value.toUpperCase())}
                                    className="h-10 rounded-md border border-white/10 bg-white/[0.035] px-3 font-mono text-sm font-bold text-white outline-none transition-colors placeholder:text-slate-700 focus:border-rose-500/40"
                                    placeholder="META"
                                    aria-label="Ticker"
                                />
                                <textarea
                                    value={analysisQuestion}
                                    onChange={event => setAnalysisQuestion(event.target.value)}
                                    onKeyDown={event => {
                                        if (event.key === 'Enter' && !event.shiftKey) {
                                            event.preventDefault();
                                            void runCompanyAnalysis();
                                        }
                                    }}
                                    rows={3}
                                    className="min-h-[96px] min-w-0 resize-none rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-sm leading-5 text-white outline-none transition-colors placeholder:text-slate-700 focus:border-rose-500/40 md:h-10 md:min-h-10"
                                    placeholder="Moat, risks, valuation lens, what changes my mind..."
                                    aria-label="Analysis question"
                                />
                                <button
                                    type="button"
                                    onClick={() => void runCompanyAnalysis()}
                                    disabled={isAnalyzing || !backendReady}
                                    className={cn(
                                        'inline-flex min-h-10 items-center justify-center gap-2 rounded-md border px-4 text-xs font-bold uppercase tracking-[0.1em] transition-colors',
                                        backendReady
                                            ? 'border-rose-500/30 bg-rose-500/15 text-rose-100 hover:bg-rose-500/20'
                                            : 'cursor-not-allowed border-white/10 bg-white/[0.025] text-slate-600'
                                    )}
                                >
                                    <Sparkles className="h-4 w-4" />
                                    {isAnalyzing ? 'Thinking' : 'Analyze'}
                                </button>
                            </div>

                            {(analysisMessage || analysisThread.length > 0 || isAnalyzing) && (
                                <div
                                    ref={analysisOutputRef}
                                    aria-live="polite"
                                    className="mt-3 rounded-lg border border-white/[0.08] bg-black/20 p-3"
                                >
                                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                                        <div className="flex items-center gap-2">
                                            <MessageSquare className="h-4 w-4 text-slate-300" />
                                            <h3 className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-300">Thread</h3>
                                        </div>
                                        <div className="flex flex-wrap gap-2">
                                            {analysisMessage && (
                                                <span className="w-fit rounded-md border border-white/[0.08] bg-white/[0.025] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-slate-500">
                                                    {analysisMessage}
                                                </span>
                                            )}
                                            {analysisThread.length > 0 && (
                                                <button
                                                    type="button"
                                                    onClick={resetBrainThread}
                                                    className="inline-flex min-h-[28px] items-center justify-center gap-1.5 rounded-md border border-white/10 bg-white/[0.035] px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-slate-300 transition-colors hover:bg-white/[0.08]"
                                                >
                                                    <RotateCcw className="h-3 w-3" />
                                                    New
                                                </button>
                                            )}
                                        </div>
                                    </div>

                                    {analysisThread.length > 0 ? (
                                        <div className="mt-3 max-h-[560px] space-y-2 overflow-auto rounded-md border border-white/[0.08] bg-[#05080e] p-2">
                                            {analysisThread.map(message => (
                                                <article
                                                    key={message.id}
                                                    className={cn(
                                                        'rounded-md border p-3',
                                                        message.role === 'user'
                                                            ? 'ml-auto max-w-[92%] border-sky-500/15 bg-sky-500/10'
                                                            : 'mr-auto max-w-[96%] border-white/[0.08] bg-white/[0.035]'
                                                    )}
                                                >
                                                    <div className="mb-2 flex items-center gap-2">
                                                        {message.role === 'user' ? (
                                                            <Target className="h-3.5 w-3.5 text-sky-300" />
                                                        ) : (
                                                            <BrainCircuit className="h-3.5 w-3.5 text-rose-300" />
                                                        )}
                                                        <span className={cn(
                                                            'text-[10px] font-bold uppercase tracking-[0.12em]',
                                                            message.role === 'user' ? 'text-sky-200' : 'text-slate-300'
                                                        )}>
                                                            {message.role === 'user' ? 'Query' : 'Answer'}
                                                        </span>
                                                    </div>
                                                    {message.role === 'assistant' ? (
                                                        <MarkdownAnswer content={message.content} />
                                                    ) : (
                                                        <div className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-100">
                                                            {message.content}
                                                        </div>
                                                    )}
                                                </article>
                                            ))}
                                            {isAnalyzing && (
                                                <article className="mr-auto max-w-[96%] rounded-md border border-white/[0.08] bg-white/[0.035] p-3">
                                                    <div className="mb-2 flex items-center gap-2">
                                                        <BrainCircuit className="h-3.5 w-3.5 text-slate-300" />
                                                        <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-300">Answer</span>
                                                    </div>
                                                    <p className="text-sm leading-6 text-slate-500">Retrieving context and preparing the answer.</p>
                                                </article>
                                            )}
                                        </div>
                                    ) : (
                                        <div className="mt-3 rounded-md border border-white/[0.08] bg-black/20 p-4 text-sm leading-6 text-slate-500">
                                            Retrieving context and preparing the answer.
                                        </div>
                                    )}

                                    {hasAssistantAnswer && (
                                        <div className="mt-3 rounded-md border border-white/[0.08] bg-black/15 p-3">
                                            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                                                <div className="flex items-center gap-2">
                                                    <FileText className="h-4 w-4 text-sky-300" />
                                                    <h3 className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-300">Sources</h3>
                                                </div>
                                                <span className="w-fit rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-[9px] font-bold uppercase tracking-[0.1em] text-slate-500">
                                                    {answerSources.length ? `${answerSources.length} context item${answerSources.length === 1 ? '' : 's'}` : 'No retrieved source context'}
                                                </span>
                                            </div>

                                            {answerSources.length > 0 ? (
                                                <div className="mt-3 grid grid-cols-1 gap-2 xl:grid-cols-2">
                                                    {answerSources.map(source => (
                                                        <article key={source.key} className="min-w-0 rounded-md border border-white/[0.07] bg-white/[0.025] p-3">
                                                            <div className="flex items-start justify-between gap-3">
                                                                <div className="min-w-0">
                                                                    <div className="flex flex-wrap items-center gap-2">
                                                                        <span className={cn(
                                                                            'rounded-md border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em]',
                                                                            sourceToneClass[source.tone]
                                                                        )}>
                                                                            {source.marker}
                                                                        </span>
                                                                        {typeof source.score === 'number' && (
                                                                            <span className="text-[10px] font-semibold text-slate-600">
                                                                                score {source.score.toFixed(3)}
                                                                            </span>
                                                                        )}
                                                                    </div>
                                                                    <h4 className="mt-2 line-clamp-2 text-sm font-black leading-5 text-white">
                                                                        {source.title}
                                                                    </h4>
                                                                    {source.detail && (
                                                                        <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-gray-500">
                                                                            {source.detail}
                                                                        </p>
                                                                    )}
                                                                </div>
                                                                <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
                                                                    {source.webUrl && (
                                                                        <a
                                                                            href={source.webUrl}
                                                                            target="_blank"
                                                                            rel="noreferrer"
                                                                            className="inline-flex min-h-[28px] items-center justify-center gap-1.5 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-emerald-200 transition-colors hover:bg-emerald-500/20"
                                                                        >
                                                                            <ExternalLink className="h-3 w-3" />
                                                                            Open
                                                                        </a>
                                                                    )}
                                                                    {source.path && (
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => void copySourcePath(source.path ?? '')}
                                                                            className="inline-flex min-h-[28px] items-center justify-center gap-1.5 rounded-md border border-white/10 bg-white/[0.035] px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-slate-300 transition-colors hover:bg-white/[0.08]"
                                                                        >
                                                                            <Copy className="h-3 w-3" />
                                                                            Path
                                                                        </button>
                                                                    )}
                                                                </div>
                                                            </div>
                                                            {source.excerpt && (
                                                                <p className="mt-2 line-clamp-3 text-xs leading-5 text-gray-400">
                                                                    {source.excerpt}
                                                                </p>
                                                            )}
                                                        </article>
                                                    ))}
                                                </div>
                                            ) : (
                                                <p className="mt-3 rounded-md border border-white/[0.06] bg-white/[0.02] p-3 text-xs leading-5 text-slate-500">
                                                    No retrieved source context for this answer.
                                                </p>
                                            )}
                                        </div>
                                    )}

                                    {hasAssistantAnswer && (
                                        <div className="mt-3 rounded-md border border-white/[0.08] bg-black/15 p-3">
                                            <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_auto]">
                                                <textarea
                                                    value={followUpQuestion}
                                                    onChange={event => setFollowUpQuestion(event.target.value)}
                                                    onKeyDown={event => {
                                                        if (event.key === 'Enter' && !event.shiftKey) {
                                                            event.preventDefault();
                                                            void runCompanyAnalysis('follow-up');
                                                        }
                                                    }}
                                                    rows={2}
                                                    className="min-h-[52px] resize-none rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-sm leading-5 text-white outline-none transition-colors placeholder:text-slate-700 focus:border-rose-500/40"
                                                    placeholder="Ask a follow-up in this thread..."
                                                    aria-label="Follow-up question"
                                                />
                                                <button
                                                    type="button"
                                                    onClick={() => void runCompanyAnalysis('follow-up')}
                                                    disabled={isAnalyzing || !backendReady || !followUpQuestion.trim()}
                                                    className={cn(
                                                        'inline-flex min-h-[42px] items-center justify-center gap-2 rounded-md border px-4 text-xs font-bold uppercase tracking-[0.1em] transition-colors md:min-w-[132px]',
                                                        backendReady && followUpQuestion.trim()
                                                            ? 'border-rose-500/30 bg-rose-500/15 text-rose-100 hover:bg-rose-500/20'
                                                            : 'cursor-not-allowed border-white/10 bg-white/[0.025] text-slate-600'
                                                    )}
                                                >
                                                    <Send className="h-4 w-4" />
                                                    Follow Up
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </section>

                        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-3 sm:p-4">
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                                <div className="flex items-center gap-2">
                                    <Search className="h-4 w-4 text-sky-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">Source Retrieval</h2>
                                </div>
                                {searchMessage && (
                                    <span className="inline-flex w-fit rounded-md border border-sky-500/20 bg-sky-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.1em] text-sky-300">
                                        {searchMessage}
                                    </span>
                                )}
                            </div>

                            <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_118px]">
                                <input
                                    value={searchQuery}
                                    onChange={event => setSearchQuery(event.target.value)}
                                    onKeyDown={event => {
                                        if (event.key === 'Enter') void runBackendSearch();
                                    }}
                                    className="h-10 min-w-0 rounded-md border border-white/10 bg-white/[0.035] px-3 text-sm text-white outline-none transition-colors placeholder:text-slate-700 focus:border-sky-500/40"
                                    placeholder="pricing power, AI infrastructure, pass reasons..."
                                />
                                <button
                                    type="button"
                                    onClick={runBackendSearch}
                                    disabled={isSearching || !backendReady}
                                    className={cn(
                                        'inline-flex min-h-10 items-center justify-center gap-2 rounded-md border px-4 text-xs font-bold uppercase tracking-[0.1em] transition-colors',
                                        backendReady
                                            ? 'border-sky-500/30 bg-sky-500/15 text-sky-200 hover:bg-sky-500/20'
                                            : 'cursor-not-allowed border-white/10 bg-white/[0.025] text-slate-600'
                                    )}
                                >
                                    <Search className="h-4 w-4" />
                                    {isSearching ? 'Searching' : 'Search'}
                                </button>
                            </div>

                            {searchResults.length > 0 && (
                                <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2">
                                    {searchResults.map(result => {
                                        const sourceName = sourceDisplayName(result);
                                        const sourcePath = result.source?.webUrl ? '' : (result.source?.relativePath || '');
                                        return (
                                            <article key={`${result.entityType}-${result.entityId}`} className="rounded-md border border-white/[0.08] bg-white/[0.025] p-3">
                                                <div className="flex items-start justify-between gap-3">
                                                    <h3 className="min-w-0 line-clamp-2 text-sm font-black leading-5 text-white">{result.title}</h3>
                                                    <span className="shrink-0 rounded-md border border-sky-500/20 bg-sky-500/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.1em] text-sky-300">
                                                        {result.entityType}
                                                    </span>
                                                </div>
                                                {sourceName && (
                                                    <div className="mt-2 flex flex-col gap-2 rounded-md border border-white/[0.06] bg-black/10 px-2.5 py-2 sm:flex-row sm:items-center sm:justify-between">
                                                        <div className="min-w-0">
                                                            <p className="truncate text-[11px] font-bold text-slate-200">{sourceName}</p>
                                                            {result.source?.relativePath && (
                                                                <p className="mt-0.5 truncate text-[10px] text-slate-600">{result.source.relativePath}</p>
                                                            )}
                                                        </div>
                                                        <div className="flex shrink-0 flex-wrap gap-1.5">
                                                            {result.source?.webUrl && (
                                                                <a
                                                                    href={result.source.webUrl}
                                                                    target="_blank"
                                                                    rel="noreferrer"
                                                                    className="inline-flex min-h-[28px] items-center justify-center gap-1.5 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-emerald-200 transition-colors hover:bg-emerald-500/20"
                                                                >
                                                                    <ExternalLink className="h-3 w-3" />
                                                                    Open
                                                                </a>
                                                            )}
                                                            {sourcePath && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => void copySourcePath(sourcePath)}
                                                                    className="inline-flex min-h-[28px] items-center justify-center gap-1.5 rounded-md border border-white/10 bg-white/[0.035] px-2 text-[9px] font-bold uppercase tracking-[0.08em] text-slate-300 transition-colors hover:bg-white/[0.08]"
                                                                >
                                                                    <Copy className="h-3 w-3" />
                                                                    Path
                                                                </button>
                                                            )}
                                                        </div>
                                                    </div>
                                                )}
                                                <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-400">{result.body}</p>
                                                {result.tags.length > 0 && (
                                                    <div className="mt-3 flex flex-wrap gap-1.5">
                                                        {result.tags.slice(0, 5).map(tag => (
                                                            <span key={tag} className="rounded-md border border-white/[0.06] bg-white/[0.03] px-2 py-1 text-[10px] font-semibold text-slate-500">
                                                                {tag}
                                                            </span>
                                                        ))}
                                                    </div>
                                                )}
                                            </article>
                                        );
                                    })}
                                </div>
                            )}
                        </section>
                    </div>

                    <aside className="space-y-4">
                        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-3 sm:p-4">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <Cloud className="h-4 w-4 text-emerald-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">Drive Library</h2>
                                </div>
                                <span className={cn(
                                    'rounded-md border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.1em]',
                                    driveConnected
                                        ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                                        : driveAuthReady
                                            ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                                            : 'border-rose-500/25 bg-rose-500/10 text-rose-300'
                                )}>
                                    {driveConnected ? 'Connected' : driveAuthReady ? 'Needs auth' : 'Needs env'}
                                </span>
                            </div>
                            <p className="mt-2 text-xs leading-5 text-slate-500">
                                {formatDriveFolder(driveStatus)}
                            </p>
                            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                                <button
                                    type="button"
                                    onClick={connectGoogleDrive}
                                    disabled={!backendReady || !driveAuthReady}
                                    className={cn(
                                        'inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                        backendReady && driveAuthReady
                                            ? 'border-emerald-500/30 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/20'
                                            : 'cursor-not-allowed border-white/10 bg-white/[0.025] text-slate-600'
                                    )}
                                >
                                    <ExternalLink className="h-3.5 w-3.5" />
                                    Connect
                                </button>
                                <button
                                    type="button"
                                    onClick={runDriveIndex}
                                    disabled={isDriveSyncing || !backendReady || !driveConnected || !driveConfigured}
                                    className={cn(
                                        'inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                        backendReady && driveConnected && driveConfigured
                                            ? 'border-emerald-500/30 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/20'
                                            : 'cursor-not-allowed border-white/10 bg-white/[0.025] text-slate-600'
                                    )}
                                >
                                    <FolderSync className="h-3.5 w-3.5" />
                                    {isDriveSyncing ? 'Syncing' : 'Sync'}
                                </button>
                            </div>
                            {driveStatus?.folderUrl && (
                                <a
                                    href={driveStatus.folderUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="mt-3 inline-flex items-center gap-1.5 text-[11px] font-semibold text-emerald-100/70 hover:text-emerald-100"
                                >
                                    Open folder
                                    <ExternalLink className="h-3 w-3" />
                                </a>
                            )}
                            {driveMessage && <p className="mt-3 text-xs font-semibold text-emerald-100/80">{driveMessage}</p>}
                        </section>

                        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-3 sm:p-4">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <Sparkles className="h-4 w-4 text-violet-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">Semantic Layer</h2>
                                </div>
                                <span className={cn(
                                    'rounded-md border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.1em]',
                                    llmStatus?.configured ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                                )}>
                                    {llmStatus?.configured ? 'Ready' : 'No key'}
                                </span>
                            </div>
                            <p className="mt-2 text-xs leading-5 text-slate-500">
                                {formatEmbeddingCoverage(embeddingStats)}
                            </p>
                            <button
                                type="button"
                                onClick={backfillEmbeddings}
                                disabled={isEmbedding || !backendReady || missingChunks <= 0}
                                className={cn(
                                    'mt-3 inline-flex min-h-9 w-full items-center justify-center gap-2 rounded-md border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                    backendReady && missingChunks > 0
                                        ? 'border-violet-500/30 bg-violet-500/15 text-violet-100 hover:bg-violet-500/20'
                                        : 'cursor-not-allowed border-white/10 bg-white/[0.025] text-slate-600'
                                )}
                            >
                                <Sparkles className="h-3.5 w-3.5" />
                                {isEmbedding ? 'Embedding' : missingChunks > 0 ? 'Embed Missing' : 'Fully Embedded'}
                            </button>
                            {embeddingMessage && <p className="mt-3 text-xs font-semibold text-violet-100/80">{embeddingMessage}</p>}
                        </section>

                        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-3 sm:p-4">
                            <div className="flex items-center gap-2">
                                <FileText className="h-4 w-4 text-cyan-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">Paste Source</h2>
                            </div>
                            <div className="mt-3 space-y-2">
                                <input
                                    value={sourceTitle}
                                    onChange={event => setSourceTitle(event.target.value)}
                                    className="h-9 w-full rounded-md border border-white/10 bg-white/[0.035] px-3 text-sm text-white outline-none transition-colors placeholder:text-slate-700 focus:border-cyan-500/40"
                                    placeholder="Source title"
                                />
                                <input
                                    value={sourceTags}
                                    onChange={event => setSourceTags(event.target.value)}
                                    className="h-9 w-full rounded-md border border-white/10 bg-white/[0.035] px-3 text-sm text-white outline-none transition-colors placeholder:text-slate-700 focus:border-cyan-500/40"
                                    placeholder="tags"
                                />
                                <textarea
                                    value={sourceBody}
                                    onChange={event => setSourceBody(event.target.value)}
                                    className="min-h-[108px] w-full resize-y rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-sm leading-6 text-white outline-none transition-colors placeholder:text-slate-700 focus:border-cyan-500/40"
                                    placeholder="Paste excerpt or note..."
                                />
                            </div>
                            <button
                                type="button"
                                onClick={ingestSourceText}
                                disabled={isIngesting || !backendReady}
                                className={cn(
                                    'mt-3 inline-flex min-h-9 w-full items-center justify-center gap-2 rounded-md border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                    backendReady
                                        ? 'border-cyan-500/30 bg-cyan-500/15 text-cyan-100 hover:bg-cyan-500/20'
                                        : 'cursor-not-allowed border-white/10 bg-white/[0.025] text-slate-600'
                                )}
                            >
                                <Plus className="h-3.5 w-3.5" />
                                {isIngesting ? 'Indexing' : 'Index Text'}
                            </button>
                            {ingestMessage && <p className="mt-3 text-xs font-semibold text-cyan-100/80">{ingestMessage}</p>}
                        </section>

                    </aside>
                </section>

                {latestIndexResults.length > 0 && (
                    <section className="mt-4 rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-3 sm:p-4">
                        <div className="flex items-center gap-2">
                            <Archive className="h-4 w-4 text-emerald-300" />
                            <h2 className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">Latest Index Run</h2>
                        </div>
                        <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2">
                            {latestIndexResults.slice(0, 10).map(result => (
                                <div key={`${result.relativePath}-${result.status}-${result.sourceId ?? ''}`} className="flex items-start justify-between gap-3 rounded-md border border-white/[0.06] bg-white/[0.025] px-3 py-2">
                                    <div className="min-w-0">
                                        <p className="truncate text-xs font-bold text-white">{result.relativePath}</p>
                                        <p className="mt-1 truncate text-[10px] text-slate-500">{result.reason ?? `${result.chunks ?? 0} chunk(s)`}</p>
                                    </div>
                                    <span className={cn('shrink-0 rounded-md border px-2 py-0.5 text-[8px] font-black uppercase tracking-[0.08em]', resultTone(result.status))}>
                                        {result.status}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </section>
                )}

                <section className="mt-4 rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-3 sm:p-4">
                    <div className="flex items-center gap-2">
                        <ServerCog className="h-4 w-4 text-gray-300" />
                        <h2 className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">Guardrails</h2>
                    </div>
                    <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
                        <p className="flex gap-2 rounded-md border border-white/[0.06] bg-white/[0.025] p-3 text-xs leading-5 text-slate-500">
                            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                            Sources stay in Drive; the brain stores metadata, extracted text, chunks, and embeddings in Supabase.
                        </p>
                        <p className="flex gap-2 rounded-md border border-white/[0.06] bg-white/[0.025] p-3 text-xs leading-5 text-slate-500">
                            <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
                            Fund-grade use still needs access controls, logs, backups, data licenses, and compliance review.
                        </p>
                    </div>
                </section>
            </main>
        </div>
    );
};
