import React, { useEffect, useMemo, useState } from 'react';
import {
    ArrowLeft,
    Archive,
    BadgeCheck,
    BookOpen,
    BrainCircuit,
    Building2,
    CheckCircle2,
    Database,
    Download,
    FileText,
    GitBranch,
    HardDrive,
    Heart,
    Layers3,
    Lightbulb,
    Network,
    Plus,
    Search,
    ServerCog,
    ShieldAlert,
    Sparkles,
    Target,
    RotateCcw,
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

type BackendState = 'checking' | 'ready' | 'offline';

const memoryTypes: {
    type: MemoryType;
    label: string;
    Icon: LucideIcon;
    activeClass: string;
}[] = [
    { type: 'liked', label: 'Liked', Icon: Heart, activeClass: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
    { type: 'passed', label: 'Passed', Icon: XCircle, activeClass: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
    { type: 'trend', label: 'Megatrend', Icon: GitBranch, activeClass: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
    { type: 'framework', label: 'Framework', Icon: BookOpen, activeClass: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
    { type: 'question', label: 'Question', Icon: Search, activeClass: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
];

const memoryTone: Record<MemoryType, { Icon: LucideIcon; className: string; label: string }> = {
    liked: { Icon: Heart, className: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20', label: 'Liked' },
    passed: { Icon: XCircle, className: 'text-rose-300 bg-rose-500/10 border-rose-500/20', label: 'Passed' },
    trend: { Icon: GitBranch, className: 'text-sky-300 bg-sky-500/10 border-sky-500/20', label: 'Megatrend' },
    framework: { Icon: BookOpen, className: 'text-amber-300 bg-amber-500/10 border-amber-500/20', label: 'Framework' },
    question: { Icon: Search, className: 'text-violet-300 bg-violet-500/10 border-violet-500/20', label: 'Question' },
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

const brainLayers = [
    {
        title: 'Library',
        detail: 'PDFs, books, annual reports, letters, transcripts, saved articles, and your own notes.',
        Icon: Archive,
        color: 'text-sky-300',
    },
    {
        title: 'Idea Extraction',
        detail: 'Turn raw sources into principles, warnings, mental models, valuation lenses, and company signals.',
        Icon: Sparkles,
        color: 'text-amber-300',
    },
    {
        title: 'Knowledge Graph',
        detail: 'Connect companies, industries, megatrends, risks, frameworks, people, and case studies.',
        Icon: Network,
        color: 'text-violet-300',
    },
    {
        title: 'Personal Memory',
        detail: 'Store why you liked, passed, bought, sold, or changed your mind about a company.',
        Icon: BrainCircuit,
        color: 'text-emerald-300',
    },
];

const analysisLoop = [
    'Retrieve your memories about the company, sector, and management pattern.',
    'Pull matching frameworks from the library and graph.',
    'Read current filings, financials, valuation, and portfolio context.',
    'Generate bull, bear, base, and what-would-change-my-mind sections.',
    'Save the final thesis, pass reason, or watchlist trigger back into memory.',
];

const databaseChoices = [
    {
        title: 'Start: SQLite',
        label: 'Best first move',
        Icon: Database,
        detail: 'Free, local, simple, and durable. Use tables for memories and documents, JSON for metadata, and FTS5 for keyword search.',
        points: ['Zero server burden', 'Easy backups', 'Perfect for one-person research brain'],
        className: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
    },
    {
        title: 'Scale: Postgres + pgvector',
        label: 'When it grows',
        Icon: ServerCog,
        detail: 'Use this when you need stronger API concurrency, richer JSONB querying, embeddings, joins, and eventually hosted access.',
        points: ['Company/thesis joins', 'Vector search', 'Cleaner multi-device API'],
        className: 'border-sky-500/25 bg-sky-500/10 text-sky-300',
    },
];

const futureEndpoints = [
    'POST /api/brain/sources',
    'POST /api/brain/memories',
    'GET /api/brain/company/:ticker/context',
    'POST /api/brain/analyze-company',
    'POST /api/brain/thesis-journal',
];

const schemaRows = [
    ['sources', 'Uploaded books, PDFs, filings, notes, links, and metadata'],
    ['chunks', 'Searchable excerpts with source, page, tags, and embeddings'],
    ['ideas', 'Principles, warnings, frameworks, trend claims, and valuation lenses'],
    ['memories', 'Why you liked, passed, bought, sold, or paused a company'],
    ['theses', 'Living company writeups with assumptions and change-my-mind triggers'],
    ['edges', 'Graph links between companies, trends, sectors, risks, and frameworks'],
];

const MEMORY_STORAGE_KEY = 'investment-brain-memories-v1';
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');

const brainApiUrl = (path: string) => `${API_BASE}${path}`;
const memoryTypeValues: MemoryType[] = ['liked', 'passed', 'trend', 'framework', 'question'];

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
        const normalized = normalizeMemoryArray(parsed);

        return normalized.length > 0 ? normalized : seedMemories;
    } catch {
        return seedMemories;
    }
};

export const InvestmentBrain: React.FC = () => {
    const [memoryType, setMemoryType] = useState<MemoryType>('trend');
    const [title, setTitle] = useState('Urbanization');
    const [body, setBody] = useState('A durable megatrend that may support infrastructure, logistics, housing quality, energy resilience, and city services over decades.');
    const [tags, setTags] = useState('urbanization, infrastructure, long-term');
    const [memories, setMemories] = useState<BrainMemory[]>(loadStoredMemories);
    const [backendState, setBackendState] = useState<BackendState>('checking');
    const [searchQuery, setSearchQuery] = useState('urbanization');
    const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
    const [searchMessage, setSearchMessage] = useState('');
    const [isSearching, setIsSearching] = useState(false);

    useEffect(() => {
        window.localStorage.setItem(MEMORY_STORAGE_KEY, JSON.stringify(memories));
    }, [memories]);

    useEffect(() => {
        let cancelled = false;

        const loadBackendMemories = async () => {
            try {
                const statusResponse = await fetch(brainApiUrl('/api/brain/status'));
                if (!statusResponse.ok) throw new Error('Brain status unavailable');

                const memoriesResponse = await fetch(brainApiUrl('/api/brain/memories?limit=200'));
                if (!memoriesResponse.ok) throw new Error('Brain memories unavailable');

                const payload = await memoriesResponse.json() as { memories?: unknown };
                const backendMemories = normalizeMemoryArray(payload.memories);

                if (!cancelled) {
                    setBackendState('ready');
                    if (backendMemories.length > 0) {
                        setMemories(backendMemories);
                    }
                }
            } catch {
                if (!cancelled) {
                    setBackendState('offline');
                }
            }
        };

        loadBackendMemories();

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
        if (backendState === 'ready') {
            try {
                await fetch(brainApiUrl(`/api/brain/memories/${id}`), { method: 'DELETE' });
            } catch {
                // Keep the UI responsive; local removal still reflects the user's intent.
            }
        }
        setMemories(current => current.filter(memory => memory.id !== id));
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
        setSearchMessage('');
        try {
            const params = new URLSearchParams({ q: cleanedQuery, limit: '50' });
            const response = await fetch(brainApiUrl(`/api/brain/search?${params.toString()}`));
            if (!response.ok) throw new Error('Search failed');

            const payload = await response.json() as { results?: SearchResult[] };
            const results = Array.isArray(payload.results) ? payload.results : [];
            setSearchResults(results);
            setSearchMessage(results.length ? `${results.length} indexed matches` : 'No indexed matches yet');
        } catch {
            setSearchResults([]);
            setSearchMessage('Backend search is unavailable');
        } finally {
            setIsSearching(false);
        }
    };

    const ActiveIcon = activeType.Icon;
    const storageLabel = backendState === 'ready'
        ? 'SQLite backend'
        : backendState === 'checking'
            ? 'Checking backend'
            : 'Saved locally';

    return (
        <div className="min-h-screen bg-background text-foreground">
            <div className="animated-top-bar h-[2px] w-full" />

            <div className="px-4 py-5 sm:px-5 md:p-8">
                <div className="mx-auto max-w-[1600px] space-y-6 md:space-y-8">
                    <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                            <a
                                href="/"
                                className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-gray-500 transition-colors hover:text-gray-300"
                            >
                                <ArrowLeft className="h-3.5 w-3.5" />
                                Dashboard
                            </a>
                            <div className="mt-4 flex items-start gap-3">
                                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-500/10">
                                    <BrainCircuit className="h-6 w-6 text-emerald-300" />
                                </div>
                                <div className="min-w-0">
                                    <h1 className="text-3xl font-black tracking-tight text-white md:text-4xl">
                                        Investment Brain
                                    </h1>
                                    <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">
                                        A synthetic research brain for documents, frameworks, megatrends, thesis memory, and company analysis in your own investing style.
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap lg:justify-end">
                            {[storageLabel, 'Private memory', 'Cited evidence', 'Your worldview', 'Company context'].map(label => (
                                <span
                                    key={label}
                                    className="inline-flex min-h-[34px] items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] px-3 text-[10px] font-bold uppercase tracking-[0.1em] text-gray-300"
                                >
                                    {label === storageLabel && <HardDrive className="mr-1.5 h-3.5 w-3.5 text-emerald-300" />}
                                    {label}
                                </span>
                            ))}
                        </div>
                    </header>

                    <section className="grid grid-cols-1 gap-4 xl:grid-cols-12 xl:gap-5">
                        <div className="xl:col-span-7 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/80 to-slate-950 p-4 sm:p-5">
                            <div className="flex items-center gap-2">
                                <Lightbulb className="h-4 w-4 text-amber-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Manual Memory Capture</h2>
                            </div>

                            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
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
                                                'inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg border px-2 text-[10px] font-bold uppercase tracking-[0.08em] transition-colors',
                                                active ? item.activeClass : 'border-white/10 bg-white/[0.03] text-gray-500 hover:text-gray-300'
                                            )}
                                        >
                                            <Icon className="h-3.5 w-3.5 shrink-0" />
                                            {item.label}
                                        </button>
                                    );
                                })}
                            </div>

                            <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-5">
                                <label className="lg:col-span-2">
                                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-gray-500">Title</span>
                                    <input
                                        value={title}
                                        onChange={event => setTitle(event.target.value)}
                                        className="mt-1 h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-emerald-500/40"
                                        placeholder="Company, trend, framework..."
                                    />
                                </label>
                                <label className="lg:col-span-3">
                                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-gray-500">Tags</span>
                                    <input
                                        value={tags}
                                        onChange={event => setTags(event.target.value)}
                                        className="mt-1 h-11 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-emerald-500/40"
                                        placeholder="moat, pass, urbanization"
                                    />
                                </label>
                                <label className="lg:col-span-5">
                                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-gray-500">Why this matters</span>
                                    <textarea
                                        value={body}
                                        onChange={event => setBody(event.target.value)}
                                        className="mt-1 min-h-[126px] w-full resize-y rounded-lg border border-white/10 bg-white/[0.04] px-3 py-3 text-sm leading-6 text-white outline-none transition-colors placeholder:text-gray-700 focus:border-emerald-500/40"
                                        placeholder="Why did you pass, like it, or care about this idea?"
                                    />
                                </label>
                            </div>

                            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                <div className="inline-flex items-center gap-2 text-xs text-gray-500">
                                    <ActiveIcon className="h-4 w-4 text-emerald-300" />
                                    Saved in this browser today. Backend sync comes with the brain API.
                                </div>
                                <button
                                    type="button"
                                    onClick={addMemory}
                                    className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/15 px-4 text-xs font-bold uppercase tracking-[0.1em] text-emerald-200 transition-colors hover:bg-emerald-500/20"
                                >
                                    <Plus className="h-4 w-4" />
                                    Add Memory
                                </button>
                            </div>
                        </div>

                        <div className="xl:col-span-5 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/80 to-slate-950 p-4 sm:p-5">
                            <div className="flex items-center gap-2">
                                <Database className="h-4 w-4 text-sky-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Database Choice</h2>
                            </div>

                            <div className="mt-4 grid grid-cols-1 gap-3">
                                {databaseChoices.map(choice => {
                                    const Icon = choice.Icon;
                                    return (
                                        <div key={choice.title} className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">
                                            <div className="flex items-start justify-between gap-3">
                                                <div className="flex items-center gap-2">
                                                    <Icon className="h-4 w-4 text-gray-300" />
                                                    <h3 className="text-sm font-black text-white">{choice.title}</h3>
                                                </div>
                                                <span className={cn('rounded border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.1em]', choice.className)}>
                                                    {choice.label}
                                                </span>
                                            </div>
                                            <p className="mt-2 text-xs leading-5 text-gray-400">{choice.detail}</p>
                                            <div className="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-3 xl:grid-cols-1">
                                                {choice.points.map(point => (
                                                    <div key={point} className="flex items-center gap-1.5 text-[11px] text-gray-500">
                                                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                                                        {point}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>

                            <div className="mt-4 rounded-lg border border-rose-500/20 bg-rose-500/10 p-3">
                                <div className="flex items-center gap-2">
                                    <ShieldAlert className="h-4 w-4 text-rose-300" />
                                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-rose-200">Not fund-ready yet</span>
                                </div>
                                <p className="mt-2 text-xs leading-5 text-rose-100/70">
                                    Local browser memory is fine for personal research. A fund-grade version needs server storage, access controls, audit logs, backups, data licenses, and compliance review.
                                </p>
                            </div>
                        </div>
                    </section>

                    <section className="grid grid-cols-1 gap-4 lg:grid-cols-4 xl:gap-5">
                        {brainLayers.map(layer => {
                            const Icon = layer.Icon;
                            return (
                                <div key={layer.title} className="rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4">
                                    <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04]">
                                        <Icon className={cn('h-4 w-4', layer.color)} />
                                    </div>
                                    <h3 className="mt-3 text-sm font-black text-white">{layer.title}</h3>
                                    <p className="mt-2 text-xs leading-5 text-gray-500">{layer.detail}</p>
                                </div>
                            );
                        })}
                    </section>

                    <section className="rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 sm:p-5">
                        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                            <div>
                                <div className="flex items-center gap-2">
                                    <Search className="h-4 w-4 text-sky-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Search All Indexed Data</h2>
                                </div>
                                <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-500">
                                    This calls the backend SQLite FTS index. It searches memories, sources, and future idea/thesis records through one retrieval layer.
                                </p>
                            </div>
                            <span className={cn(
                                'inline-flex w-fit items-center rounded-lg border px-3 py-2 text-[10px] font-bold uppercase tracking-[0.1em]',
                                backendState === 'ready'
                                    ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
                                    : backendState === 'checking'
                                        ? 'border-amber-500/25 bg-amber-500/10 text-amber-300'
                                        : 'border-rose-500/25 bg-rose-500/10 text-rose-300'
                            )}>
                                {backendState === 'ready' ? 'Backend ready' : backendState === 'checking' ? 'Checking' : 'Local fallback'}
                            </span>
                        </div>

                        <div className="mt-4 flex flex-col gap-3 md:flex-row">
                            <input
                                value={searchQuery}
                                onChange={event => setSearchQuery(event.target.value)}
                                onKeyDown={event => {
                                    if (event.key === 'Enter') {
                                        void runBackendSearch();
                                    }
                                }}
                                className="h-11 min-w-0 flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-sky-500/40"
                                placeholder="Search urbanization, pass reasons, frameworks..."
                            />
                            <button
                                type="button"
                                onClick={runBackendSearch}
                                disabled={isSearching || backendState !== 'ready'}
                                className={cn(
                                    'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border px-4 text-xs font-bold uppercase tracking-[0.1em] transition-colors',
                                    backendState === 'ready'
                                        ? 'border-sky-500/30 bg-sky-500/15 text-sky-200 hover:bg-sky-500/20'
                                        : 'cursor-not-allowed border-white/10 bg-white/[0.03] text-gray-600'
                                )}
                            >
                                <Search className="h-4 w-4" />
                                {isSearching ? 'Searching' : 'Search'}
                            </button>
                        </div>

                        {searchMessage && (
                            <p className="mt-3 text-xs font-semibold text-gray-500">{searchMessage}</p>
                        )}

                        {searchResults.length > 0 && (
                            <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
                                {searchResults.map(result => (
                                    <article key={`${result.entityType}-${result.entityId}`} className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">
                                        <div className="flex items-start justify-between gap-3">
                                            <h3 className="text-sm font-black text-white">{result.title}</h3>
                                            <span className="rounded border border-sky-500/20 bg-sky-500/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.1em] text-sky-300">
                                                {result.entityType}
                                            </span>
                                        </div>
                                        <p className="mt-2 line-clamp-3 text-xs leading-5 text-gray-400">{result.body}</p>
                                        <div className="mt-3 flex flex-wrap gap-1.5">
                                            {result.tags.slice(0, 6).map(tag => (
                                                <span key={tag} className="rounded border border-white/[0.06] bg-white/[0.03] px-2 py-1 text-[10px] font-semibold text-gray-500">
                                                    {tag}
                                                </span>
                                            ))}
                                        </div>
                                    </article>
                                ))}
                            </div>
                        )}
                    </section>

                    <section className="grid grid-cols-1 gap-4 xl:grid-cols-12 xl:gap-5">
                        <div className="xl:col-span-7 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 sm:p-5">
                            <div className="flex items-center gap-2">
                                <Target className="h-4 w-4 text-rose-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Company Analysis Loop</h2>
                            </div>
                            <div className="mt-4 space-y-2">
                                {analysisLoop.map((step, index) => (
                                    <div key={step} className="grid grid-cols-[34px_1fr] gap-3 rounded-lg border border-white/[0.06] bg-white/[0.025] p-3">
                                        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] font-mono text-xs font-black text-emerald-300">
                                            {index + 1}
                                        </div>
                                        <p className="self-center text-sm leading-5 text-gray-300">{step}</p>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="xl:col-span-5 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 sm:p-5">
                            <div className="flex items-center gap-2">
                                <ServerCog className="h-4 w-4 text-cyan-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">API Spine</h2>
                            </div>
                            <div className="mt-4 space-y-2">
                                {futureEndpoints.map(endpoint => (
                                    <div key={endpoint} className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2 font-mono text-xs text-gray-300">
                                        {endpoint}
                                    </div>
                                ))}
                            </div>
                            <div className="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3">
                                <div className="flex items-center gap-2">
                                    <ShieldAlert className="h-4 w-4 text-amber-300" />
                                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-amber-200">Design rule</span>
                                </div>
                                <p className="mt-2 text-xs leading-5 text-amber-100/70">
                                    Every answer should separate evidence, inference, and your personal prior. That keeps the brain useful instead of overconfident.
                                </p>
                            </div>
                        </div>
                    </section>

                    <section className="grid grid-cols-1 gap-4 xl:grid-cols-12 xl:gap-5">
                        <div className="xl:col-span-7 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 sm:p-5">
                            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                                <div className="flex items-center gap-2">
                                    <Layers3 className="h-4 w-4 text-violet-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Memory Stream</h2>
                                    <span className="rounded border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] font-bold text-gray-500">
                                        {memories.length}
                                    </span>
                                </div>
                                <div className="flex gap-2">
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
                            <div className="mt-4 grid grid-cols-1 gap-3">
                                {memories.map(memory => {
                                    const tone = memoryTone[memory.type];
                                    const Icon = tone.Icon;
                                    return (
                                        <article key={memory.id} className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">
                                            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                                                <div className="flex items-center gap-2">
                                                    <span className={cn('inline-flex h-7 w-7 items-center justify-center rounded-lg border', tone.className)}>
                                                        <Icon className="h-3.5 w-3.5" />
                                                    </span>
                                                    <h3 className="text-sm font-black text-white">{memory.title}</h3>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <span className={cn('inline-flex w-fit items-center rounded border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.1em]', tone.className)}>
                                                        {tone.label}
                                                    </span>
                                                    <button
                                                        type="button"
                                                        onClick={() => deleteMemory(memory.id)}
                                                        className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-gray-600 transition-colors hover:border-rose-500/30 hover:text-rose-300"
                                                        title="Delete memory"
                                                        aria-label={`Delete ${memory.title}`}
                                                    >
                                                        <Trash2 className="h-3.5 w-3.5" />
                                                    </button>
                                                </div>
                                            </div>
                                            <p className="mt-3 text-sm leading-6 text-gray-400">{memory.body}</p>
                                            <div className="mt-3 flex flex-wrap gap-1.5">
                                                {memory.tags.map(tag => (
                                                    <span key={tag} className="rounded border border-white/[0.06] bg-white/[0.03] px-2 py-1 text-[10px] font-semibold text-gray-500">
                                                        {tag}
                                                    </span>
                                                ))}
                                            </div>
                                        </article>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="xl:col-span-5 rounded-xl border border-white/[0.08] bg-gradient-to-br from-slate-900/70 to-slate-950/90 p-4 sm:p-5">
                            <div className="flex items-center gap-2">
                                <Building2 className="h-4 w-4 text-emerald-300" />
                                <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Core Tables</h2>
                            </div>
                            <div className="mt-4 divide-y divide-white/[0.06] overflow-hidden rounded-lg border border-white/[0.08]">
                                {schemaRows.map(([name, detail]) => (
                                    <div key={name} className="grid grid-cols-1 gap-1 bg-white/[0.025] px-3 py-3 sm:grid-cols-[110px_1fr]">
                                        <span className="font-mono text-xs font-black text-emerald-300">{name}</span>
                                        <span className="text-xs leading-5 text-gray-400">{detail}</span>
                                    </div>
                                ))}
                            </div>
                            <div className="mt-4 rounded-lg border border-white/[0.08] bg-black/20 p-3">
                                <div className="flex items-center gap-2">
                                    <FileText className="h-4 w-4 text-gray-300" />
                                    <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-gray-400">Next backend move</span>
                                </div>
                                <p className="mt-2 text-xs leading-5 text-gray-500">
                                    Add a small `/api/brain` service first. It can write local SQLite rows today and swap to Postgres later without changing the page.
                                </p>
                            </div>
                        </div>
                    </section>

                    <section className="rounded-xl border border-white/[0.08] bg-gradient-to-r from-emerald-950/20 via-slate-900/70 to-slate-950 p-4 sm:p-5">
                        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                            <div>
                                <div className="flex items-center gap-2">
                                    <BadgeCheck className="h-4 w-4 text-emerald-300" />
                                    <h2 className="text-[11px] font-bold uppercase tracking-[0.14em] text-gray-400">Build Order</h2>
                                </div>
                                <p className="mt-2 max-w-4xl text-sm leading-6 text-gray-300">
                                    Ship memory capture first, document ingestion second, retrieval third, and company analysis last. That order makes the system learn your taste before it tries to sound smart.
                                </p>
                            </div>
                            <a
                                href="/"
                                className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-4 text-xs font-bold uppercase tracking-[0.1em] text-gray-300 transition-colors hover:bg-white/[0.07] hover:text-white"
                            >
                                <ArrowLeft className="h-4 w-4" />
                                Back to Dashboard
                            </a>
                        </div>
                    </section>
                </div>
            </div>
        </div>
    );
};
