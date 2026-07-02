import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    ArrowLeft,
    Archive,
    BookOpen,
    BrainCircuit,
    CheckCircle2,
    Cloud,
    Database,
    Download,
    ExternalLink,
    FileText,
    FolderSync,
    GitBranch,
    HardDrive,
    Heart,
    Layers3,
    Lightbulb,
    Plus,
    RotateCcw,
    Search,
    ServerCog,
    ShieldAlert,
    Sparkles,
    Target,
    Trash2,
    XCircle,
    type LucideIcon,
} from 'lucide-react';
import { cn } from '../lib/utils';

type MemoryType = 'liked' | 'passed' | 'trend' | 'framework' | 'question';

type BrainMemory = {
    id: number;
    type: MemoryType;
    title: string;
    body: string;
    tags: string[];
};

type SearchResult = {
    entityType: string;
    entityId: number;
    title: string;
    body: string;
    tags: string[];
    rank?: number;
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

type BrainStatus = {
    state?: string;
    database?: string;
    storage?: string;
    search?: string;
    vectorSearch?: string;
    counts?: BrainCounts;
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

type LocalIndexerStatus = {
    configuredRoot: string;
    exists: boolean;
    customPathsAllowed: boolean;
    supportedExtensions: string[];
    pdfAvailable: boolean;
    storageMode: string;
};

type LocalIndexResult = {
    path: string;
    relativePath: string;
    status: 'indexed' | 'skipped' | 'error';
    reason?: string;
    sourceId?: number;
    chunks?: number;
    bytes?: number;
};

type LocalIndexResponse = {
    root: string;
    summary: {
        found: number;
        indexed: number;
        skipped: number;
        errors: number;
    };
    results: LocalIndexResult[];
    counts?: BrainCounts;
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
    };
    results: DriveIndexResult[];
    counts?: BrainCounts;
};

type EmbeddingBackfillResponse = {
    model: string;
    requested: number;
    embedded: number;
    errors: { id?: number; title?: string; error: string }[];
    counts?: BrainCounts;
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
    };
};

type BackendState = 'checking' | 'ready' | 'offline';

const MEMORY_STORAGE_KEY = 'investment-brain-memories-v1';
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');
const memoryTypeValues: MemoryType[] = ['liked', 'passed', 'trend', 'framework', 'question'];

const brainApiUrl = (path: string) => `${API_BASE}${path}`;

const memoryTypes: {
    type: MemoryType;
    label: string;
    Icon: LucideIcon;
    activeClass: string;
}[] = [
    { type: 'liked', label: 'Liked', Icon: Heart, activeClass: 'border-emerald-500/35 bg-emerald-500/15 text-emerald-200' },
    { type: 'passed', label: 'Passed', Icon: XCircle, activeClass: 'border-rose-500/35 bg-rose-500/15 text-rose-200' },
    { type: 'trend', label: 'Megatrend', Icon: GitBranch, activeClass: 'border-sky-500/35 bg-sky-500/15 text-sky-200' },
    { type: 'framework', label: 'Framework', Icon: BookOpen, activeClass: 'border-amber-500/35 bg-amber-500/15 text-amber-200' },
    { type: 'question', label: 'Question', Icon: Search, activeClass: 'border-violet-500/35 bg-violet-500/15 text-violet-200' },
];

const memoryTone: Record<MemoryType, { Icon: LucideIcon; className: string; label: string }> = {
    liked: { Icon: Heart, className: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300', label: 'Liked' },
    passed: { Icon: XCircle, className: 'border-rose-500/25 bg-rose-500/10 text-rose-300', label: 'Passed' },
    trend: { Icon: GitBranch, className: 'border-sky-500/25 bg-sky-500/10 text-sky-300', label: 'Megatrend' },
    framework: { Icon: BookOpen, className: 'border-amber-500/25 bg-amber-500/10 text-amber-300', label: 'Framework' },
    question: { Icon: Search, className: 'border-violet-500/25 bg-violet-500/10 text-violet-300', label: 'Question' },
};

const seedMemories: BrainMemory[] = [
    {
        id: 1,
        type: 'trend',
        title: 'Urbanization as a long-running force',
        body: 'More dense cities should keep pushing demand toward infrastructure, logistics, utilities, housing quality, elevators, payments, and energy resilience. Watch for capital intensity and regulation.',
        tags: ['urbanization', 'infrastructure', 'multi-decade'],
    },
    {
        id: 2,
        type: 'passed',
        title: 'Pass memory example: cyclically cheap industrial',
        body: 'Passed because earnings looked peak-cycle, leverage was rising, and the cheap multiple did not compensate for weak pricing power.',
        tags: ['pass', 'cyclical', 'leverage'],
    },
    {
        id: 3,
        type: 'liked',
        title: 'Like memory example: founder-led compounder',
        body: 'Liked because reinvestment runway, owner-operator incentives, high gross margins, and conservative balance sheet matched my preferred pattern.',
        tags: ['compounder', 'owner-operator', 'quality'],
    },
];

const formatTags = (value: string) =>
    value
        .split(',')
        .map(tag => tag.trim())
        .filter(Boolean)
        .slice(0, 6);

const isMemoryType = (value: unknown): value is MemoryType =>
    typeof value === 'string' && memoryTypeValues.includes(value as MemoryType);

const normalizeStoredMemory = (value: unknown): BrainMemory | null => {
    if (!value || typeof value !== 'object') return null;

    const item = value as Record<string, unknown>;
    if (
        typeof item.id !== 'number' ||
        !isMemoryType(item.type) ||
        typeof item.title !== 'string' ||
        typeof item.body !== 'string'
    ) {
        return null;
    }

    const tags = Array.isArray(item.tags)
        ? item.tags.filter((tag): tag is string => typeof tag === 'string').slice(0, 6)
        : [];

    return {
        id: item.id,
        type: item.type,
        title: item.title,
        body: item.body,
        tags,
    };
};

const normalizeMemoryArray = (value: unknown) => {
    if (!Array.isArray(value)) return [];
    return value
        .map(normalizeStoredMemory)
        .filter((memory): memory is BrainMemory => memory !== null);
};

const loadStoredMemories = () => {
    if (typeof window === 'undefined') return seedMemories;

    const raw = window.localStorage.getItem(MEMORY_STORAGE_KEY);
    if (!raw) return seedMemories;

    try {
        const parsed = JSON.parse(raw) as unknown;
        return normalizeMemoryArray(parsed);
    } catch {
        return seedMemories;
    }
};

const formatStorage = (storage?: string) => {
    if (storage === 'postgres_pgvector') return 'Supabase pgvector';
    if (storage === 'sqlite') return 'SQLite';
    return 'Not connected';
};

const formatSearchDetail = (status: BrainStatus | null) => {
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
    const [memoryType, setMemoryType] = useState<MemoryType>('trend');
    const [title, setTitle] = useState('Urbanization');
    const [body, setBody] = useState('A durable megatrend that may support infrastructure, logistics, housing quality, energy resilience, and city services over decades.');
    const [tags, setTags] = useState('urbanization, infrastructure, long-term');
    const [memories, setMemories] = useState<BrainMemory[]>(loadStoredMemories);
    const [backendState, setBackendState] = useState<BackendState>('checking');
    const [brainStatus, setBrainStatus] = useState<BrainStatus | null>(null);
    const [searchQuery, setSearchQuery] = useState('pricing power AI infrastructure');
    const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
    const [searchMessage, setSearchMessage] = useState('');
    const [isSearching, setIsSearching] = useState(false);
    const [backendCounts, setBackendCounts] = useState<BrainCounts | null>(null);
    const [sourceTitle, setSourceTitle] = useState('Source note');
    const [sourceBody, setSourceBody] = useState('Paste a memo, transcript excerpt, book passage, framework, or article note here. The brain will store it as a source, split it into chunks, and make it searchable.');
    const [sourceTags, setSourceTags] = useState('framework, source');
    const [ingestMessage, setIngestMessage] = useState('');
    const [isIngesting, setIsIngesting] = useState(false);
    const [localIndexerStatus, setLocalIndexerStatus] = useState<LocalIndexerStatus | null>(null);
    const [indexRootPath, setIndexRootPath] = useState('');
    const [isIndexing, setIsIndexing] = useState(false);
    const [indexMessage, setIndexMessage] = useState('');
    const [indexResults, setIndexResults] = useState<LocalIndexResult[]>([]);
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
    const analysisOutputRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        window.localStorage.setItem(MEMORY_STORAGE_KEY, JSON.stringify(memories));
    }, [memories]);

    useEffect(() => {
        if (!isAnalyzing && !analysisAnswer) return;
        window.setTimeout(() => {
            analysisOutputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 80);
    }, [isAnalyzing, analysisAnswer]);

    useEffect(() => {
        let cancelled = false;

        const loadBackend = async () => {
            try {
                const statusResponse = await fetch(brainApiUrl('/api/brain/status'));
                if (!statusResponse.ok) throw new Error('Brain status unavailable');
                const status = await statusResponse.json() as BrainStatus;

                let nextIndexerStatus: LocalIndexerStatus | null = null;
                let nextDriveStatus: DriveIndexerStatus | null = null;

                try {
                    const indexerResponse = await fetch(brainApiUrl('/api/brain/index/local/status'));
                    if (indexerResponse.ok) {
                        nextIndexerStatus = await indexerResponse.json() as LocalIndexerStatus;
                    }
                } catch {
                    nextIndexerStatus = null;
                }

                try {
                    const driveResponse = await fetch(brainApiUrl('/api/brain/index/drive/status'));
                    if (driveResponse.ok) {
                        nextDriveStatus = await driveResponse.json() as DriveIndexerStatus;
                    }
                } catch {
                    nextDriveStatus = null;
                }

                const memoriesResponse = await fetch(brainApiUrl('/api/brain/memories?limit=200'));
                if (!memoriesResponse.ok) throw new Error('Brain memories unavailable');

                const payload = await memoriesResponse.json() as { memories?: unknown };
                const backendMemories = normalizeMemoryArray(payload.memories);

                if (!cancelled) {
                    setBackendState('ready');
                    setBrainStatus(status);
                    setBackendCounts(status.counts ?? null);
                    setLlmStatus(status.llm ?? null);
                    setLocalIndexerStatus(nextIndexerStatus);
                    setDriveStatus(nextDriveStatus);
                    setIndexRootPath(nextIndexerStatus?.configuredRoot ?? '');
                    setMemories(backendMemories);
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

    const activeType = useMemo(
        () => memoryTypes.find(item => item.type === memoryType) ?? memoryTypes[0],
        [memoryType]
    );

    const addMemory = async () => {
        const cleanedTitle = title.trim();
        const cleanedBody = body.trim();
        if (!cleanedTitle || !cleanedBody) return;

        const nextMemory: BrainMemory = {
            id: Date.now(),
            type: memoryType,
            title: cleanedTitle,
            body: cleanedBody,
            tags: formatTags(tags),
        };

        if (backendState === 'ready') {
            try {
                const response = await fetch(brainApiUrl('/api/brain/memories'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(nextMemory),
                });

                if (response.ok) {
                    const payload = await response.json() as { memory?: unknown };
                    const saved = normalizeStoredMemory(payload.memory) ?? nextMemory;
                    setMemories(current => [saved, ...current]);
                    setBackendCounts(current => ({ ...(current ?? {}), memories: (current?.memories ?? memories.length) + 1 }));
                } else {
                    setMemories(current => [nextMemory, ...current]);
                }
            } catch {
                setMemories(current => [nextMemory, ...current]);
            }
        } else {
            setMemories(current => [nextMemory, ...current]);
        }

        setTitle('');
        setBody('');
        setTags('');
    };

    const deleteMemory = async (id: number) => {
        setMemories(current => current.filter(memory => memory.id !== id));
        setSearchResults(current => current.filter(result => result.entityType !== 'memory' || result.entityId !== id));

        if (backendState === 'ready') {
            try {
                await fetch(brainApiUrl(`/api/brain/memories/${id}`), { method: 'DELETE' });
                setBackendCounts(current => ({
                    ...(current ?? {}),
                    memories: Math.max(0, (current?.memories ?? memories.length) - 1),
                }));
            } catch {
                // The visual removal should still honor the user's intent.
            }
        }
    };

    const resetMemories = () => {
        setMemories(seedMemories);
    };

    const exportMemories = () => {
        const file = new Blob([JSON.stringify(memories, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(file);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'investment-brain-memories.json';
        link.click();
        URL.revokeObjectURL(url);
    };

    const runBackendSearch = async () => {
        const cleanedQuery = searchQuery.trim();
        if (!cleanedQuery) return;

        setIsSearching(true);
        setSearchMessage('Searching your indexed sources...');
        try {
            const params = new URLSearchParams({ q: cleanedQuery, limit: '12' });
            const response = await fetch(brainApiUrl(`/api/brain/search?${params.toString()}`));
            if (!response.ok) {
                const payload = await response.json().catch(() => null) as { detail?: string } | null;
                throw new Error(payload?.detail ?? 'Search failed');
            }

            const payload = await response.json() as { results?: SearchResult[]; timings?: { totalMs?: number } };
            const results = Array.isArray(payload.results) ? payload.results : [];
            const totalSeconds = typeof payload.timings?.totalMs === 'number'
                ? ` in ${(payload.timings.totalMs / 1000).toFixed(1)}s`
                : '';
            setSearchResults(results);
            setSearchMessage(results.length ? `${results.length} match${results.length === 1 ? '' : 'es'}${totalSeconds}` : `No matches yet${totalSeconds}`);
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

    const runLocalIndex = async () => {
        if (backendState !== 'ready') return;

        setIsIndexing(true);
        setIndexMessage('');
        setIndexResults([]);
        try {
            const requestedRoot = indexRootPath.trim();
            const useCustomRoot = localIndexerStatus?.customPathsAllowed
                && requestedRoot
                && requestedRoot !== localIndexerStatus.configuredRoot;
            const response = await fetch(brainApiUrl('/api/brain/index/local'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rootPath: useCustomRoot ? requestedRoot : undefined,
                    limitFiles: 250,
                    force: false,
                }),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => null) as { detail?: string } | null;
                throw new Error(payload?.detail ?? 'Local index failed');
            }

            const payload = await response.json() as LocalIndexResponse;
            setBackendCounts(payload.counts ?? null);
            setIndexResults(payload.results ?? []);
            setIndexMessage(`${payload.summary.indexed} indexed, ${payload.summary.skipped} skipped, ${payload.summary.errors} errors`);

            if (payload.root && payload.root !== localIndexerStatus?.configuredRoot) {
                setIndexRootPath(payload.root);
            }
        } catch (error) {
            setIndexMessage(error instanceof Error ? error.message : 'Local index failed');
        } finally {
            setIsIndexing(false);
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
            const response = await fetch(brainApiUrl('/api/brain/index/drive'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    limitFiles: 100,
                    force: false,
                }),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => null) as { detail?: string } | null;
                throw new Error(payload?.detail ?? 'Google Drive sync failed');
            }

            const payload = await response.json() as DriveIndexResponse;
            setBackendCounts(payload.counts ?? null);
            setDriveResults(payload.results ?? []);
            setDriveMessage(`${payload.summary.indexed} indexed, ${payload.summary.skipped} skipped, ${payload.summary.errors} errors`);

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
            const response = await fetch(brainApiUrl('/api/brain/embeddings/backfill'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ limit: 50, force: false }),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => null) as { detail?: string } | null;
                throw new Error(payload?.detail ?? 'Embedding failed');
            }

            const payload = await response.json() as EmbeddingBackfillResponse;
            setBackendCounts(payload.counts ?? null);
            setEmbeddingMessage(`${payload.embedded}/${payload.requested} embedded with ${payload.model}${payload.errors.length ? `, ${payload.errors.length} error(s)` : ''}.`);
        } catch (error) {
            setEmbeddingMessage(error instanceof Error ? error.message : 'Embedding failed');
        } finally {
            setIsEmbedding(false);
        }
    };

    const runCompanyAnalysis = async () => {
        const ticker = analysisTicker.trim();
        if (!ticker || backendState !== 'ready') return;

        setIsAnalyzing(true);
        setAnalysisMessage('Retrieving your brain context, then asking Gemini...');
        setAnalysisAnswer('');
        try {
            const response = await fetch(brainApiUrl('/api/brain/analyze-company'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticker,
                    question: analysisQuestion.trim(),
                    limit: 5,
                    useSemantic: true,
                }),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => null) as { detail?: string } | null;
                throw new Error(payload?.detail ?? 'Analysis failed');
            }

            const payload = await response.json() as BrainAnalysisResponse;
            setAnalysisAnswer(payload.answer);
            const totalSeconds = typeof payload.timings?.totalMs === 'number'
                ? ` in ${(payload.timings.totalMs / 1000).toFixed(1)}s`
                : '';
            const generationSeconds = typeof payload.timings?.generationMs === 'number'
                ? `, Gemini ${(payload.timings.generationMs / 1000).toFixed(1)}s`
                : '';
            setAnalysisMessage(`${payload.model} with ${payload.embeddingModel}${totalSeconds}${generationSeconds}`);
        } catch (error) {
            setAnalysisMessage(error instanceof Error ? error.message : 'Analysis failed');
        } finally {
            setIsAnalyzing(false);
        }
    };

    const backendReady = backendState === 'ready';
    const storageLabel = formatStorage(brainStatus?.storage);
    const ActiveIcon = activeType.Icon;
    const counts = backendCounts ?? {};
    const driveConnected = Boolean(driveStatus?.connected);
    const driveConfigured = Boolean(driveStatus?.configured);
    const driveAuthReady = Boolean(driveStatus?.authConfigured);
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
                detail: 'Authorize the Drive folder once, then this page can sync your research library.',
                label: 'Connect Drive',
                Icon: ExternalLink,
                onClick: connectGoogleDrive,
                disabled: false,
            }
            : driveConnected && (counts.chunks ?? 0) === 0
                ? {
                    title: 'Sync your Drive library',
                    detail: 'Index supported PDFs, docs, notes, and text files into Supabase.',
                    label: isDriveSyncing ? 'Syncing' : 'Sync Drive',
                    Icon: FolderSync,
                    onClick: runDriveIndex,
                    disabled: isDriveSyncing,
                }
                : (counts.chunks ?? 0) > 0
                    ? {
                        title: 'Keep semantic search fresh',
                        detail: 'Embed missing chunks so the brain can retrieve ideas by meaning.',
                        label: isEmbedding ? 'Embedding' : 'Embed Missing',
                        Icon: Sparkles,
                        onClick: backfillEmbeddings,
                        disabled: isEmbedding,
                    }
                    : {
                        title: 'Start with one source or memory',
                        detail: 'Paste a note, save a thesis memory, or connect Drive to seed the brain.',
                        label: 'Ready',
                        Icon: CheckCircle2,
                        onClick: undefined,
                        disabled: true,
                    };

    const statusCards = [
        {
            label: 'Storage',
            value: storageLabel,
            detail: formatSearchDetail(brainStatus),
            Icon: Database,
            className: brainStatus?.storage === 'postgres_pgvector' ? 'text-emerald-300' : 'text-amber-300',
        },
        {
            label: 'AI',
            value: llmStatus?.configured ? 'Gemini ready' : 'Missing key',
            detail: llmStatus?.embeddingModel ?? 'embedding model',
            Icon: Sparkles,
            className: llmStatus?.configured ? 'text-violet-300' : 'text-amber-300',
        },
        {
            label: 'Drive',
            value: driveConnected ? 'Connected' : driveAuthReady ? 'Needs auth' : 'Not connected',
            detail: driveStatus?.folderId ? 'folder configured' : 'folder missing',
            Icon: Cloud,
            className: driveConnected ? 'text-emerald-300' : driveAuthReady ? 'text-amber-300' : 'text-gray-400',
        },
        {
            label: 'Indexed',
            value: `${counts.sources ?? 0} sources`,
            detail: `${counts.chunks ?? 0} chunks, ${counts.memories ?? memories.length} memories`,
            Icon: Layers3,
            className: 'text-sky-300',
        },
    ];

    const latestIndexResults = driveResults.length > 0 ? driveResults : indexResults;

    return (
        <div className="min-h-screen bg-[#05070d] text-foreground">
            <div className="animated-top-bar h-[2px] w-full" />

            <main className="mx-auto max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8">
                <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
                    <div className="min-w-0">
                        <a
                            href="/"
                            className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-gray-500 transition-colors hover:text-gray-300"
                        >
                            <ArrowLeft className="h-3.5 w-3.5" />
                            Dashboard
                        </a>
                        <div className="mt-4 flex items-start gap-3">
                            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-500/10">
                                <BrainCircuit className="h-6 w-6 text-emerald-300" />
                            </div>
                            <div className="min-w-0">
                                <h1 className="text-3xl font-black tracking-tight text-white md:text-4xl">
                                    Investment Brain
                                </h1>
                                <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">
                                    Search your sources, save your reasoning, and ask company questions against your own frameworks.
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="flex flex-wrap gap-2">
                        <span className={cn(
                            'inline-flex min-h-[34px] items-center rounded-lg border px-3 text-[10px] font-bold uppercase tracking-[0.1em]',
                            backendReady ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                        )}>
                            {backendReady ? 'Backend ready' : backendState === 'checking' ? 'Checking' : 'Offline'}
                        </span>
                        <span className="inline-flex min-h-[34px] items-center rounded-lg border border-white/10 bg-white/[0.04] px-3 text-[10px] font-bold uppercase tracking-[0.1em] text-gray-300">
                            {storageLabel}
                        </span>
                    </div>
                </header>

                <section className="mt-5 grid grid-cols-1 gap-3 lg:grid-cols-4">
                    {statusCards.map(item => {
                        const Icon = item.Icon;
                        return (
                            <div key={item.label} className="rounded-xl border border-white/[0.08] bg-white/[0.035] p-4">
                                <div className="flex items-center justify-between gap-3">
                                    <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500">{item.label}</span>
                                    <Icon className={cn('h-4 w-4', item.className)} />
                                </div>
                                <p className="mt-3 truncate text-lg font-black text-white">{item.value}</p>
                                <p className="mt-1 truncate text-xs text-gray-500">{item.detail}</p>
                            </div>
                        );
                    })}
                </section>

                <section className="mt-4 rounded-xl border border-white/[0.08] bg-gradient-to-r from-slate-900/85 to-slate-950/95 p-4 sm:p-5">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                        <div className="flex min-w-0 items-start gap-3">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-500/10">
                                <nextAction.Icon className="h-5 w-5 text-emerald-300" />
                            </div>
                            <div className="min-w-0">
                                <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500">Next action</p>
                                <h2 className="mt-1 text-xl font-black text-white">{nextAction.title}</h2>
                                <p className="mt-1 text-sm leading-6 text-gray-400">{nextAction.detail}</p>
                                {(driveMessage || embeddingMessage || indexMessage) && (
                                    <p className="mt-2 text-xs font-semibold text-emerald-100/80">
                                        {driveMessage || embeddingMessage || indexMessage}
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
                                    className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-4 text-xs font-bold uppercase tracking-[0.1em] text-gray-300 transition-colors hover:bg-white/[0.07]"
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
                                    'inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border px-4 text-xs font-bold uppercase tracking-[0.1em] transition-colors',
                                    nextAction.disabled
                                        ? 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
                                        : 'border-emerald-500/30 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/20'
                                )}
                            >
                                <nextAction.Icon className="h-4 w-4" />
                                {nextAction.label}
                            </button>
                        </div>
                    </div>
                </section>

                <section className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)]">
                    <div className="space-y-5">
                        <section className="rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                                <div>
                                    <div className="flex items-center gap-2">
                                        <Target className="h-4 w-4 text-rose-300" />
                                        <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Ask The Brain</h2>
                                    </div>
                                    <p className="mt-2 text-sm leading-6 text-gray-500">
                                        Uses your memories, indexed chunks, and semantic retrieval to answer in your investing style.
                                    </p>
                                </div>
                                <span className={cn(
                                    'inline-flex w-fit rounded border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.1em]',
                                    llmStatus?.configured ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                                )}>
                                    {llmStatus?.configured ? 'Gemini ready' : 'API key missing'}
                                </span>
                            </div>

                            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-[120px_1fr_auto]">
                                <input
                                    value={analysisTicker}
                                    onChange={event => setAnalysisTicker(event.target.value.toUpperCase())}
                                    className="h-11 rounded-lg border border-white/10 bg-white/[0.04] px-3 font-mono text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-rose-500/40"
                                    placeholder="META"
                                    aria-label="Ticker"
                                />
                                <input
                                    value={analysisQuestion}
                                    onChange={event => setAnalysisQuestion(event.target.value)}
                                    onKeyDown={event => {
                                        if (event.key === 'Enter') void runCompanyAnalysis();
                                    }}
                                    className="h-11 min-w-0 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-rose-500/40"
                                    placeholder="Moat, risks, valuation lens, what changes my mind..."
                                    aria-label="Analysis question"
                                />
                                <button
                                    type="button"
                                    onClick={runCompanyAnalysis}
                                    disabled={isAnalyzing || !backendReady}
                                    className={cn(
                                        'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border px-4 text-xs font-bold uppercase tracking-[0.1em] transition-colors',
                                        backendReady
                                            ? 'border-rose-500/30 bg-rose-500/15 text-rose-100 hover:bg-rose-500/20'
                                            : 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
                                    )}
                                >
                                    <Sparkles className="h-4 w-4" />
                                    {isAnalyzing ? 'Thinking' : 'Analyze'}
                                </button>
                            </div>

                            {(analysisMessage || analysisAnswer || isAnalyzing) && (
                                <div
                                    ref={analysisOutputRef}
                                    aria-live="polite"
                                    className="mt-4 rounded-xl border border-rose-500/20 bg-rose-950/10 p-3 sm:p-4"
                                >
                                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                                        <div className="flex items-center gap-2">
                                            <BrainCircuit className="h-4 w-4 text-rose-300" />
                                            <h3 className="text-[11px] font-bold uppercase tracking-[0.14em] text-rose-100">Brain Answer</h3>
                                        </div>
                                        {analysisMessage && (
                                            <span className="w-fit rounded border border-white/[0.08] bg-black/20 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-gray-400">
                                                {analysisMessage}
                                            </span>
                                        )}
                                    </div>

                                    {analysisAnswer ? (
                                        <div className="mt-3 max-h-[520px] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/[0.08] bg-black/25 p-4 text-sm leading-6 text-gray-100">
                                            {analysisAnswer}
                                        </div>
                                    ) : (
                                        <div className="mt-3 rounded-lg border border-white/[0.08] bg-black/20 p-4 text-sm leading-6 text-gray-400">
                                            Retrieving context and preparing the answer here.
                                        </div>
                                    )}
                                </div>
                            )}
                        </section>

                        <section className="rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                                <div>
                                    <div className="flex items-center gap-2">
                                        <Search className="h-4 w-4 text-sky-300" />
                                        <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Search</h2>
                                    </div>
                                    <p className="mt-2 text-sm leading-6 text-gray-500">
                                        Search memories, sources, and chunks before asking the model.
                                    </p>
                                </div>
                                {searchMessage && (
                                    <span className="inline-flex w-fit rounded border border-sky-500/20 bg-sky-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.1em] text-sky-300">
                                        {searchMessage}
                                    </span>
                                )}
                            </div>

                            <div className="mt-4 flex flex-col gap-3 md:flex-row">
                                <input
                                    value={searchQuery}
                                    onChange={event => setSearchQuery(event.target.value)}
                                    onKeyDown={event => {
                                        if (event.key === 'Enter') void runBackendSearch();
                                    }}
                                    className="h-11 min-w-0 flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-sky-500/40"
                                    placeholder="pricing power, AI infrastructure, pass reasons..."
                                />
                                <button
                                    type="button"
                                    onClick={runBackendSearch}
                                    disabled={isSearching || !backendReady}
                                    className={cn(
                                        'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border px-4 text-xs font-bold uppercase tracking-[0.1em] transition-colors',
                                        backendReady
                                            ? 'border-sky-500/30 bg-sky-500/15 text-sky-200 hover:bg-sky-500/20'
                                            : 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
                                    )}
                                >
                                    <Search className="h-4 w-4" />
                                    {isSearching ? 'Searching' : 'Search'}
                                </button>
                            </div>

                            {searchResults.length > 0 && (
                                <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
                                    {searchResults.map(result => (
                                        <article key={`${result.entityType}-${result.entityId}`} className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">
                                            <div className="flex items-start justify-between gap-3">
                                                <h3 className="min-w-0 text-sm font-black text-white">{result.title}</h3>
                                                <span className="shrink-0 rounded border border-sky-500/20 bg-sky-500/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.1em] text-sky-300">
                                                    {result.entityType}
                                                </span>
                                            </div>
                                            <p className="mt-2 line-clamp-3 text-xs leading-5 text-gray-400">{result.body}</p>
                                            {result.tags.length > 0 && (
                                                <div className="mt-3 flex flex-wrap gap-1.5">
                                                    {result.tags.slice(0, 5).map(tag => (
                                                        <span key={tag} className="rounded border border-white/[0.06] bg-white/[0.03] px-2 py-1 text-[10px] font-semibold text-gray-500">
                                                            {tag}
                                                        </span>
                                                    ))}
                                                </div>
                                            )}
                                        </article>
                                    ))}
                                </div>
                            )}
                        </section>
                    </div>

                    <aside className="space-y-5">
                        <section className="rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <Cloud className="h-4 w-4 text-emerald-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Drive Library</h2>
                                </div>
                                <span className={cn(
                                    'rounded border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.1em]',
                                    driveConnected
                                        ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                                        : driveAuthReady
                                            ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                                            : 'border-rose-500/25 bg-rose-500/10 text-rose-300'
                                )}>
                                    {driveConnected ? 'Connected' : driveAuthReady ? 'Needs auth' : 'Needs env'}
                                </span>
                            </div>
                            <p className="mt-3 text-xs leading-5 text-gray-500">
                                {formatDriveFolder(driveStatus)}
                            </p>
                            <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
                                <button
                                    type="button"
                                    onClick={connectGoogleDrive}
                                    disabled={!backendReady || !driveAuthReady}
                                    className={cn(
                                        'inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                        backendReady && driveAuthReady
                                            ? 'border-emerald-500/30 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/20'
                                            : 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
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
                                        'inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                        backendReady && driveConnected && driveConfigured
                                            ? 'border-emerald-500/30 bg-emerald-500/15 text-emerald-100 hover:bg-emerald-500/20'
                                            : 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
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

                        <section className="rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                            <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2">
                                    <Sparkles className="h-4 w-4 text-violet-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Semantic Layer</h2>
                                </div>
                                <span className={cn(
                                    'rounded border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.1em]',
                                    llmStatus?.configured ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                                )}>
                                    {llmStatus?.configured ? 'Ready' : 'No key'}
                                </span>
                            </div>
                            <p className="mt-3 text-xs leading-5 text-gray-500">
                                Attach embeddings after new files or notes are indexed.
                            </p>
                            <button
                                type="button"
                                onClick={backfillEmbeddings}
                                disabled={isEmbedding || !backendReady}
                                className={cn(
                                    'mt-4 inline-flex min-h-[40px] w-full items-center justify-center gap-2 rounded-lg border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                    backendReady
                                        ? 'border-violet-500/30 bg-violet-500/15 text-violet-100 hover:bg-violet-500/20'
                                        : 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
                                )}
                            >
                                <Sparkles className="h-3.5 w-3.5" />
                                {isEmbedding ? 'Embedding' : 'Embed Missing'}
                            </button>
                            {embeddingMessage && <p className="mt-3 text-xs font-semibold text-violet-100/80">{embeddingMessage}</p>}
                        </section>

                        <section className="rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                            <div className="flex items-center gap-2">
                                <FileText className="h-4 w-4 text-cyan-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Paste Source</h2>
                            </div>
                            <div className="mt-4 space-y-3">
                                <input
                                    value={sourceTitle}
                                    onChange={event => setSourceTitle(event.target.value)}
                                    className="h-10 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-cyan-500/40"
                                    placeholder="Source title"
                                />
                                <input
                                    value={sourceTags}
                                    onChange={event => setSourceTags(event.target.value)}
                                    className="h-10 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-cyan-500/40"
                                    placeholder="tags"
                                />
                                <textarea
                                    value={sourceBody}
                                    onChange={event => setSourceBody(event.target.value)}
                                    className="min-h-[118px] w-full resize-y rounded-lg border border-white/10 bg-white/[0.04] px-3 py-3 text-sm leading-6 text-white outline-none transition-colors placeholder:text-gray-700 focus:border-cyan-500/40"
                                    placeholder="Paste note, filing excerpt, or framework..."
                                />
                            </div>
                            <button
                                type="button"
                                onClick={ingestSourceText}
                                disabled={isIngesting || !backendReady}
                                className={cn(
                                    'mt-3 inline-flex min-h-[40px] w-full items-center justify-center gap-2 rounded-lg border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                    backendReady
                                        ? 'border-cyan-500/30 bg-cyan-500/15 text-cyan-100 hover:bg-cyan-500/20'
                                        : 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
                                )}
                            >
                                <Plus className="h-3.5 w-3.5" />
                                {isIngesting ? 'Indexing' : 'Index Text'}
                            </button>
                            {ingestMessage && <p className="mt-3 text-xs font-semibold text-cyan-100/80">{ingestMessage}</p>}
                        </section>

                        <section className="rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                            <div className="flex items-center gap-2">
                                <HardDrive className="h-4 w-4 text-gray-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Local Folder</h2>
                            </div>
                            <p className="mt-3 break-all font-mono text-[11px] leading-5 text-gray-500">
                                {localIndexerStatus?.configuredRoot ?? 'Local scanner unavailable'}
                            </p>
                            {localIndexerStatus?.customPathsAllowed && (
                                <input
                                    value={indexRootPath}
                                    onChange={event => setIndexRootPath(event.target.value)}
                                    className="mt-3 h-10 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 font-mono text-xs text-white outline-none transition-colors placeholder:text-gray-700 focus:border-cyan-500/40"
                                    placeholder="Local library folder path"
                                />
                            )}
                            <button
                                type="button"
                                onClick={runLocalIndex}
                                disabled={isIndexing || !backendReady}
                                className={cn(
                                    'mt-3 inline-flex min-h-[38px] w-full items-center justify-center gap-2 rounded-lg border px-3 text-[10px] font-bold uppercase tracking-[0.1em] transition-colors',
                                    backendReady
                                        ? 'border-white/10 bg-white/[0.04] text-gray-300 hover:bg-white/[0.07]'
                                        : 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
                                )}
                            >
                                <Search className="h-3.5 w-3.5" />
                                {isIndexing ? 'Scanning' : 'Scan Local'}
                            </button>
                            {indexMessage && <p className="mt-3 text-xs font-semibold text-gray-400">{indexMessage}</p>}
                        </section>
                    </aside>
                </section>

                {latestIndexResults.length > 0 && (
                    <section className="mt-5 rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                        <div className="flex items-center gap-2">
                            <Archive className="h-4 w-4 text-emerald-300" />
                            <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Latest Index Run</h2>
                        </div>
                        <div className="mt-4 grid grid-cols-1 gap-2 lg:grid-cols-2">
                            {latestIndexResults.slice(0, 10).map(result => (
                                <div key={`${result.relativePath}-${result.status}-${result.sourceId ?? ''}`} className="flex items-start justify-between gap-3 rounded-lg border border-white/[0.06] bg-white/[0.025] px-3 py-2">
                                    <div className="min-w-0">
                                        <p className="truncate text-xs font-bold text-white">{result.relativePath}</p>
                                        <p className="mt-1 truncate text-[10px] text-gray-500">{result.reason ?? `${result.chunks ?? 0} chunk(s)`}</p>
                                    </div>
                                    <span className={cn('shrink-0 rounded border px-2 py-0.5 text-[8px] font-black uppercase tracking-[0.08em]', resultTone(result.status))}>
                                        {result.status}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </section>
                )}

                <section className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
                    <section className="rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                            <div className="flex items-center gap-2">
                                <Lightbulb className="h-4 w-4 text-amber-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Save A Memory</h2>
                            </div>
                            <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
                                {memoryTypes.map(item => {
                                    const Icon = item.Icon;
                                    const active = item.type === memoryType;
                                    return (
                                        <button
                                            key={item.type}
                                            type="button"
                                            onClick={() => setMemoryType(item.type)}
                                            aria-pressed={active}
                                            className={cn(
                                                'inline-flex min-h-[34px] items-center justify-center gap-1.5 rounded-lg border px-2 text-[9px] font-bold uppercase tracking-[0.08em] transition-colors',
                                                active ? item.activeClass : 'border-white/10 bg-white/[0.03] text-gray-500 hover:text-gray-300'
                                            )}
                                        >
                                            <Icon className="h-3.5 w-3.5 shrink-0" />
                                            {item.label}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,220px)_minmax(0,1fr)]">
                            <div className="space-y-3">
                                <input
                                    value={title}
                                    onChange={event => setTitle(event.target.value)}
                                    className="h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-emerald-500/40"
                                    placeholder="Company or idea"
                                />
                                <input
                                    value={tags}
                                    onChange={event => setTags(event.target.value)}
                                    className="h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-emerald-500/40"
                                    placeholder="tags"
                                />
                            </div>
                            <textarea
                                value={body}
                                onChange={event => setBody(event.target.value)}
                                className="min-h-[110px] w-full resize-y rounded-lg border border-white/10 bg-white/[0.04] px-3 py-3 text-sm leading-6 text-white outline-none transition-colors placeholder:text-gray-700 focus:border-emerald-500/40"
                                placeholder="Why did you like, pass, sell, or question this?"
                            />
                        </div>

                        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                            <p className="inline-flex items-center gap-2 text-xs text-gray-500">
                                <ActiveIcon className="h-4 w-4 text-emerald-300" />
                                Saved to backend when available and mirrored in browser storage.
                            </p>
                            <button
                                type="button"
                                onClick={addMemory}
                                className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/15 px-4 text-xs font-bold uppercase tracking-[0.1em] text-emerald-200 transition-colors hover:bg-emerald-500/20"
                            >
                                <Plus className="h-4 w-4" />
                                Add Memory
                            </button>
                        </div>
                    </section>

                    <section className="rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                        <div className="flex items-center gap-2">
                            <ServerCog className="h-4 w-4 text-gray-300" />
                            <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Guardrails</h2>
                        </div>
                        <div className="mt-4 space-y-3 text-xs leading-5 text-gray-500">
                            <p className="flex gap-2">
                                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                                Sources stay in Drive; the brain stores metadata, extracted text, chunks, and embeddings.
                            </p>
                            <p className="flex gap-2">
                                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
                                Fund-grade use still needs access controls, logs, backups, data licenses, and compliance review.
                            </p>
                        </div>
                    </section>
                </section>

                <section className="mt-5 rounded-xl border border-white/[0.08] bg-slate-950/75 p-4 sm:p-5">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="flex items-center gap-2">
                            <Layers3 className="h-4 w-4 text-violet-300" />
                            <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Memory Stream</h2>
                            <span className="rounded border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] font-bold text-gray-500">
                                {memories.length}
                            </span>
                        </div>
                        <div className="grid grid-cols-2 gap-2 sm:flex">
                            <button
                                type="button"
                                onClick={exportMemories}
                                className="inline-flex min-h-[34px] items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-[10px] font-bold uppercase tracking-[0.08em] text-gray-300 transition-colors hover:bg-white/[0.07]"
                            >
                                <Download className="h-3.5 w-3.5" />
                                Export
                            </button>
                            <button
                                type="button"
                                onClick={resetMemories}
                                className="inline-flex min-h-[34px] items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-[10px] font-bold uppercase tracking-[0.08em] text-gray-300 transition-colors hover:bg-white/[0.07]"
                            >
                                <RotateCcw className="h-3.5 w-3.5" />
                                Reset
                            </button>
                        </div>
                    </div>

                    <div className="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-2">
                        {memories.length === 0 && (
                            <div className="rounded-lg border border-dashed border-white/[0.12] bg-white/[0.025] p-5 text-center xl:col-span-2">
                                <Archive className="mx-auto h-5 w-5 text-gray-500" />
                                <p className="mt-3 text-sm font-bold text-gray-300">No saved memories yet</p>
                                <p className="mt-1 text-xs leading-5 text-gray-500">Add a thesis, pass reason, framework, or megatrend to start building the brain.</p>
                            </div>
                        )}
                        {memories.map(memory => {
                            const tone = memoryTone[memory.type];
                            const Icon = tone.Icon;
                            return (
                                <article key={memory.id} className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0">
                                            <div className="flex min-w-0 items-center gap-2">
                                                <span className={cn('inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border', tone.className)}>
                                                    <Icon className="h-3.5 w-3.5" />
                                                </span>
                                                <h3 className="truncate text-sm font-black text-white">{memory.title}</h3>
                                            </div>
                                            <p className="mt-2 line-clamp-3 text-xs leading-5 text-gray-400">{memory.body}</p>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => deleteMemory(memory.id)}
                                            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-gray-600 transition-colors hover:border-rose-500/30 hover:text-rose-300"
                                            title="Delete memory"
                                            aria-label={`Delete ${memory.title}`}
                                        >
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                    <div className="mt-3 flex flex-wrap gap-1.5">
                                        <span className={cn('rounded border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.1em]', tone.className)}>
                                            {tone.label}
                                        </span>
                                        {memory.tags.slice(0, 5).map(tag => (
                                            <span key={tag} className="rounded border border-white/[0.06] bg-white/[0.03] px-2 py-1 text-[10px] font-semibold text-gray-500">
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                </article>
                            );
                        })}
                    </div>
                </section>
            </main>
        </div>
    );
};
