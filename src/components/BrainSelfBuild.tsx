import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    Check,
    ChevronDown,
    ChevronRight,
    CircleDashed,
    ExternalLink,
    GitPullRequest,
    Hammer,
    LoaderCircle,
    RefreshCw,
    ShieldCheck,
    Wand2,
    X,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { api, brainErrorText } from '../lib/brainApi';

type CodeStatus = {
    available: boolean;
    reason?: string;
    github?: {
        configured: boolean;
        repo?: string;
        baseBranch?: string;
        repoUrl?: string | null;
    };
    llm?: {
        configured: boolean;
        codeModel?: string;
        thinkingLevel?: string;
    };
    guardrails?: {
        writablePaths?: string[];
        protectedPaths?: string[];
        protectedPrefixes?: string[];
        maxChangedFiles?: number;
        maxOpenProposals?: number;
        allowDependencies?: boolean;
        allowSelfEdit?: boolean;
        allowMerge?: boolean;
    };
};

type ChangePreview = {
    path: string;
    action: 'create' | 'edit' | 'delete';
    reason?: string;
    diff?: string;
};

type PullRequestSummary = {
    number?: number;
    title?: string;
    state?: string;
    url?: string;
    headRef?: string;
    createdAt?: string;
    changedFiles?: number;
};

type ProposalResult = {
    action?: string;
    message?: string;
    summary?: string;
    rationale?: string;
    risks?: string[];
    followUps?: string[];
    model?: string;
    branch?: string;
    baseSha?: string;
    contextPaths?: string[];
    changes?: ChangePreview[];
    pullRequest?: PullRequestSummary;
};

type CheckRun = {
    name?: string;
    state?: string;
    url?: string | null;
};

type ProposalChecks = {
    state?: string;
    checks?: CheckRun[];
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

const ACTION_TONE: Record<ChangePreview['action'], string> = {
    create: 'border-emerald-400/25 bg-emerald-400/[0.08] text-emerald-200',
    edit: 'border-cyan-400/25 bg-cyan-400/[0.08] text-cyan-200',
    delete: 'border-rose-400/25 bg-rose-400/[0.08] text-rose-200',
};

const CHECK_TONE: Record<string, string> = {
    passing: 'border-emerald-500/25 bg-emerald-500/[0.08] text-emerald-200',
    failing: 'border-rose-500/25 bg-rose-500/[0.08] text-rose-200',
    pending: 'border-amber-500/25 bg-amber-500/[0.08] text-amber-200',
    none: 'border-white/[0.08] bg-white/[0.025] text-slate-400',
    unknown: 'border-white/[0.08] bg-white/[0.025] text-slate-400',
};

const CHECK_LABEL: Record<string, string> = {
    passing: 'Checks passed',
    failing: 'Checks failed',
    pending: 'Checks running',
    none: 'No checks',
    unknown: 'Checks unclear',
};

/** Colour a unified diff without pulling in a syntax highlighter. */
const DiffBlock: React.FC<{ diff: string }> = ({ diff }) => (
    <pre className="max-h-72 overflow-auto rounded-md border border-white/[0.06] bg-black/40 p-3 text-[10.5px] leading-[1.55]">
        {diff.split('\n').map((line, index) => (
            <div
                key={index}
                className={cn(
                    'whitespace-pre font-mono',
                    line.startsWith('+') && !line.startsWith('+++') && 'text-emerald-300',
                    line.startsWith('-') && !line.startsWith('---') && 'text-rose-300',
                    line.startsWith('@@') && 'text-violet-300',
                    (line.startsWith('+++') || line.startsWith('---')) && 'text-slate-500',
                    !line.startsWith('+') && !line.startsWith('-') && !line.startsWith('@@') && 'text-slate-400',
                )}
            >
                {line || ' '}
            </div>
        ))}
    </pre>
);

export const BrainSelfBuild: React.FC<{ disabled?: boolean }> = ({ disabled = false }) => {
    const [status, setStatus] = useState<CodeStatus | null>(null);
    const [isStatusLoading, setIsStatusLoading] = useState(true);
    const [request, setRequest] = useState('');
    const [isWorking, setIsWorking] = useState(false);
    const [workingLabel, setWorkingLabel] = useState('');
    const [result, setResult] = useState<ProposalResult | null>(null);
    const [error, setError] = useState('');
    const [expandedPath, setExpandedPath] = useState<string | null>(null);
    const [proposals, setProposals] = useState<PullRequestSummary[]>([]);
    const [checksByNumber, setChecksByNumber] = useState<Record<number, ProposalChecks>>({});
    const [busyNumber, setBusyNumber] = useState<number | null>(null);
    const [isGuardrailsOpen, setIsGuardrailsOpen] = useState(false);

    const guardrails = status?.guardrails;
    const ready = Boolean(status?.available) && !disabled;

    const loadStatus = useCallback(async () => {
        setIsStatusLoading(true);
        try {
            const response = await fetch(api('/api/brain/code/status'));
            if (!response.ok) throw new Error(await brainErrorText(response, 'Could not read self-build status.'));
            setStatus(await response.json() as CodeStatus);
        } catch (caught) {
            setStatus(null);
            setError(caught instanceof Error ? caught.message : 'Could not read self-build status.');
        } finally {
            setIsStatusLoading(false);
        }
    }, []);

    const loadProposals = useCallback(async () => {
        try {
            const response = await fetch(api('/api/brain/code/proposals?state=open&limit=10'));
            if (!response.ok) throw new Error(await brainErrorText(response, 'Could not list open proposals.'));
            const payload = await response.json() as { proposals?: PullRequestSummary[] };
            setProposals(payload.proposals ?? []);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'Could not list open proposals.');
        }
    }, []);

    useEffect(() => {
        void loadStatus();
    }, [loadStatus]);

    useEffect(() => {
        if (status?.available) void loadProposals();
    }, [status?.available, loadProposals]);

    const propose = useCallback(async (openPullRequest: boolean) => {
        const trimmed = request.trim();
        if (!ready || trimmed.length < 8 || isWorking) return;
        setIsWorking(true);
        setWorkingLabel(openPullRequest ? 'Writing code and opening a pull request' : 'Planning the change');
        setError('');
        setResult(null);
        setExpandedPath(null);
        try {
            const response = await fetch(api('/api/brain/code/propose'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ request: trimmed, openPullRequest }),
            });
            if (!response.ok) throw new Error(await brainErrorText(response, 'The self-build agent could not complete this change.'));
            const payload = await response.json() as ProposalResult;
            setResult(payload);
            setExpandedPath(payload.changes?.[0]?.path ?? null);
            if (payload.pullRequest?.number) void loadProposals();
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : 'The self-build agent could not complete this change.');
        } finally {
            setIsWorking(false);
            setWorkingLabel('');
        }
    }, [ready, request, isWorking, loadProposals]);

    const refreshChecks = useCallback(async (number: number) => {
        setBusyNumber(number);
        try {
            const response = await fetch(api(`/api/brain/code/proposals/${number}`));
            if (!response.ok) throw new Error(await brainErrorText(response, `Could not read checks for #${number}.`));
            const payload = await response.json() as ProposalChecks;
            setChecksByNumber(current => ({ ...current, [number]: payload }));
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : `Could not read checks for #${number}.`);
        } finally {
            setBusyNumber(null);
        }
    }, []);

    const mergeProposal = useCallback(async (number: number) => {
        setBusyNumber(number);
        setError('');
        try {
            const response = await fetch(api(`/api/brain/code/proposals/${number}/merge`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ requireGreenChecks: true, method: 'squash' }),
            });
            if (!response.ok) throw new Error(await brainErrorText(response, `Could not merge #${number}.`));
            await loadProposals();
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : `Could not merge #${number}.`);
        } finally {
            setBusyNumber(null);
        }
    }, [loadProposals]);

    const unavailableReason = useMemo(() => {
        if (isStatusLoading || status?.available) return '';
        if (!status) return 'The backend did not answer the self-build status check.';
        if (status.reason) return status.reason;
        if (!status.github?.configured) return 'GitHub is not connected. Set BRAIN_GITHUB_TOKEN and BRAIN_GITHUB_REPO on the backend.';
        if (!status.llm?.configured) return 'Google AI Studio is not configured. Set GOOGLE_AI_API_KEY on the backend.';
        return 'Self-build is unavailable.';
    }, [isStatusLoading, status]);

    return (
        <section className="rounded-lg border border-white/[0.08] bg-[#090e17]/95 p-4">
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Hammer className="h-4 w-4 text-amber-300" />
                    <h2 className="text-[11px] font-bold uppercase tracking-[0.11em] text-slate-300">Self-build</h2>
                </div>
                <div className="flex items-center gap-1.5">
                    {status?.llm?.codeModel && (
                        <span className="rounded border border-white/[0.08] px-1.5 py-1 font-mono text-[9px] text-slate-500">{status.llm.codeModel}</span>
                    )}
                    <button
                        type="button"
                        onClick={() => { void loadStatus(); void loadProposals(); }}
                        className="flex h-7 w-7 items-center justify-center rounded-md border border-white/10 text-slate-400 transition-colors hover:bg-white/[0.07] hover:text-white"
                        aria-label="Refresh self-build status"
                    >
                        {isStatusLoading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    </button>
                </div>
            </div>

            <p className="mt-2 text-[11px] leading-5 text-slate-500">
                Describe a change to this dashboard. Gemini writes the code, pushes it to a branch on{' '}
                {status?.github?.repoUrl ? (
                    <a href={status.github.repoUrl} target="_blank" rel="noreferrer" className="font-medium text-slate-400 underline decoration-dotted hover:text-amber-200">
                        {status.github.repo}
                    </a>
                ) : (
                    <span className="font-medium text-slate-400">GitHub</span>
                )}
                , and opens a pull request. You review and merge it — nothing deploys on its own.
            </p>

            {!isStatusLoading && !status?.available && (
                <p className="mt-3 rounded-md border border-amber-400/15 bg-amber-400/[0.04] px-3 py-2 text-xs leading-5 text-amber-200/80">{unavailableReason}</p>
            )}

            <textarea
                value={request}
                onChange={event => setRequest(event.target.value)}
                disabled={!ready || isWorking}
                rows={3}
                maxLength={4000}
                placeholder="Add a widget above the returns heatmap showing the three largest single-name exposures and their share of gross."
                className="mt-3 w-full resize-y rounded-md border border-white/[0.09] bg-white/[0.025] px-3 py-2 text-sm leading-6 text-white outline-none placeholder:text-slate-600 focus:border-amber-500/35 disabled:cursor-not-allowed disabled:text-slate-600"
            />

            <div className="mt-2 grid grid-cols-2 gap-2">
                <Button type="button" onClick={() => void propose(false)} disabled={!ready || isWorking || request.trim().length < 8}>
                    {isWorking && workingLabel.startsWith('Planning') ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />} Preview diff
                </Button>
                <Button type="button" tone="primary" onClick={() => void propose(true)} disabled={!ready || isWorking || request.trim().length < 8}>
                    {isWorking && workingLabel.startsWith('Writing') ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <GitPullRequest className="h-3.5 w-3.5" />} Open PR
                </Button>
            </div>

            {isWorking && (
                <p className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
                    <LoaderCircle className="h-3.5 w-3.5 animate-spin text-amber-300" /> {workingLabel}. This takes up to a few minutes.
                </p>
            )}

            {error && (
                <p className="mt-3 flex items-start gap-2 rounded-md border border-rose-400/20 bg-rose-400/[0.05] px-3 py-2 text-xs leading-5 text-rose-200/90">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span className="min-w-0">{error}</span>
                </p>
            )}

            {result && (
                <div className="mt-3 border-t border-white/[0.07] pt-3">
                    {result.pullRequest?.url ? (
                        <a
                            href={result.pullRequest.url}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center justify-between gap-2 rounded-md border border-emerald-500/25 bg-emerald-500/[0.07] px-3 py-2 text-xs font-semibold text-emerald-100 transition-colors hover:bg-emerald-500/[0.13]"
                        >
                            <span className="min-w-0 truncate">#{result.pullRequest.number} {result.pullRequest.title}</span>
                            <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                        </a>
                    ) : (
                        <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">Preview only — nothing pushed</p>
                    )}

                    {result.summary && <p className="mt-2 text-xs leading-5 text-slate-300">{result.summary}</p>}
                    {result.rationale && <p className="mt-1.5 text-[11px] leading-5 text-slate-500">{result.rationale}</p>}

                    {!!result.changes?.length && (
                        <div className="mt-3 space-y-1.5">
                            {result.changes.map(change => {
                                const isOpen = expandedPath === change.path;
                                return (
                                    <article key={change.path} className="rounded-md border border-white/[0.06] bg-black/15">
                                        <button
                                            type="button"
                                            onClick={() => setExpandedPath(isOpen ? null : change.path)}
                                            className="flex w-full items-center gap-2 px-3 py-2 text-left"
                                        >
                                            {isOpen ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-500" />}
                                            <span className={cn('shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.06em]', ACTION_TONE[change.action])}>{change.action}</span>
                                            <span className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-slate-300">{change.path}</span>
                                        </button>
                                        {isOpen && (
                                            <div className="border-t border-white/[0.06] px-3 py-2">
                                                {change.reason && <p className="mb-2 text-[11px] leading-5 text-slate-500">{change.reason}</p>}
                                                {change.diff ? <DiffBlock diff={change.diff} /> : <p className="text-[11px] text-slate-600">No diff was returned for this file.</p>}
                                            </div>
                                        )}
                                    </article>
                                );
                            })}
                        </div>
                    )}

                    {!!result.risks?.length && (
                        <div className="mt-3 rounded-md border border-amber-400/15 bg-amber-400/[0.04] px-3 py-2">
                            <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-amber-200/80">Risks the agent flagged</p>
                            <ul className="mt-1 space-y-1">
                                {result.risks.map(risk => <li key={risk} className="text-[11px] leading-5 text-amber-200/70">· {risk}</li>)}
                            </ul>
                        </div>
                    )}

                    {!!result.contextPaths?.length && (
                        <p className="mt-2 truncate text-[10px] text-slate-600" title={result.contextPaths.join('\n')}>
                            Read {result.contextPaths.length} file(s): {result.contextPaths.join(', ')}
                        </p>
                    )}
                </div>
            )}

            {!!proposals.length && (
                <div className="mt-4 border-t border-white/[0.07] pt-3">
                    <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-slate-500">Open proposals · {proposals.length}</p>
                    <div className="mt-2 space-y-2">
                        {proposals.map(proposal => {
                            const number = proposal.number ?? 0;
                            const checks = checksByNumber[number];
                            const state = checks?.state ?? 'unknown';
                            const failing = (checks?.checks ?? []).filter(check => ['failure', 'error', 'timed_out', 'cancelled'].includes(String(check.state)));
                            return (
                                <article key={number} className="rounded-md border border-white/[0.06] bg-black/15 px-3 py-2.5">
                                    <div className="flex items-start justify-between gap-2">
                                        <a href={proposal.url} target="_blank" rel="noreferrer" className="min-w-0 text-xs font-semibold leading-5 text-slate-200 transition-colors hover:text-amber-200">
                                            #{number} {proposal.title}
                                        </a>
                                        <ExternalLink className="mt-1 h-3 w-3 shrink-0 text-slate-600" />
                                    </div>
                                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                                        {checks ? (
                                            <span className={cn('inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.06em]', CHECK_TONE[state] ?? CHECK_TONE.unknown)}>
                                                {state === 'passing' ? <Check className="h-3 w-3" /> : state === 'failing' ? <X className="h-3 w-3" /> : <CircleDashed className="h-3 w-3" />}
                                                {CHECK_LABEL[state] ?? state}
                                            </span>
                                        ) : null}
                                        <Button type="button" onClick={() => void refreshChecks(number)} disabled={busyNumber === number} className="min-h-6 px-1.5 text-[9px]">
                                            {busyNumber === number ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Checks
                                        </Button>
                                        {guardrails?.allowMerge && (
                                            <Button
                                                type="button"
                                                tone="success"
                                                onClick={() => void mergeProposal(number)}
                                                disabled={busyNumber === number || state !== 'passing'}
                                                title={state === 'passing' ? 'Squash and merge this proposal' : 'Merging is only offered once checks pass'}
                                                className="min-h-6 px-1.5 text-[9px]"
                                            >
                                                <Check className="h-3 w-3" /> Merge
                                            </Button>
                                        )}
                                    </div>
                                    {failing.length > 0 && (
                                        <p className="mt-1.5 text-[10px] leading-4 text-rose-300/80">Failing: {failing.map(check => check.name).join(', ')}</p>
                                    )}
                                </article>
                            );
                        })}
                    </div>
                </div>
            )}

            {guardrails && (
                <div className="mt-4 border-t border-white/[0.07] pt-3">
                    <button type="button" onClick={() => setIsGuardrailsOpen(open => !open)} className="flex w-full items-center gap-2 text-left">
                        {isGuardrailsOpen ? <ChevronDown className="h-3.5 w-3.5 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-500" />}
                        <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" />
                        <span className="text-[9px] font-bold uppercase tracking-[0.1em] text-slate-400">Guardrails</span>
                    </button>
                    {isGuardrailsOpen && (
                        <dl className="mt-2 space-y-2 text-[10px] leading-4">
                            <div>
                                <dt className="font-bold uppercase tracking-[0.08em] text-slate-600">Can write</dt>
                                <dd className="mt-0.5 font-mono text-slate-400">{(guardrails.writablePaths ?? []).join(' · ')}</dd>
                            </div>
                            <div>
                                <dt className="font-bold uppercase tracking-[0.08em] text-slate-600">Never writes</dt>
                                <dd className="mt-0.5 font-mono text-slate-400">{[...(guardrails.protectedPrefixes ?? []), ...(guardrails.protectedPaths ?? [])].join(' · ')}</dd>
                            </div>
                            <div>
                                <dt className="font-bold uppercase tracking-[0.08em] text-slate-600">Limits</dt>
                                <dd className="mt-0.5 text-slate-400">
                                    {guardrails.maxChangedFiles} files per change · {guardrails.maxOpenProposals} open proposals ·{' '}
                                    {guardrails.allowMerge ? 'merge from dashboard on' : 'merge only on GitHub'} ·{' '}
                                    {guardrails.allowDependencies ? 'dependency edits on' : 'no dependency edits'}
                                </dd>
                            </div>
                        </dl>
                    )}
                </div>
            )}
        </section>
    );
};
