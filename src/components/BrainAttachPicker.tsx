import React, { useEffect, useRef, useState } from 'react';
import { FileText, Link2, LoaderCircle, Paperclip, Search, X } from 'lucide-react';
import { cn } from '../lib/utils';
import { api, brainErrorText } from '../lib/brainApi';
import { attachmentLabel, looksLikeDriveReference, type AttachableSource } from '../lib/attachments';

/** Attach exact files to the next question.
 *
 *  One field does both jobs. Typed words search the library; a pasted Google Drive
 *  link is indexed on demand (it can live anywhere the connected account can open)
 *  and attached. Attached files are read in full for that question, ahead of any
 *  pinned "every answer" files, and do not need to be embedded first.
 */
export const BrainAttachPicker: React.FC<{
    open: boolean;
    onClose: () => void;
    attached: AttachableSource[];
    onAdd: (source: AttachableSource) => void;
    onRemove: (sourceId: number) => void;
    max: number;
}> = ({ open, onClose, attached, onAdd, onRemove, max }) => {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<AttachableSource[]>([]);
    const [isSearching, setIsSearching] = useState(false);
    const [isLinking, setIsLinking] = useState(false);
    const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const attachedIds = new Set(attached.flatMap(source => typeof source.id === 'number' ? [source.id] : []));
    const full = attachedIds.size >= max;
    const isLink = looksLikeDriveReference(query);

    useEffect(() => {
        if (!open) return;
        setMessage(null);
        const timer = window.setTimeout(() => inputRef.current?.focus(), 30);
        const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKey);
        return () => { window.clearTimeout(timer); window.removeEventListener('keydown', onKey); };
    }, [open, onClose]);

    useEffect(() => {
        if (!open || isLink) return;
        const controller = new AbortController();
        const timer = window.setTimeout(async () => {
            setIsSearching(true);
            try {
                const params = new URLSearchParams({ limit: '20' });
                if (query.trim()) params.set('q', query.trim());
                const response = await fetch(api(`/api/brain/sources?${params.toString()}`), { signal: controller.signal });
                if (!response.ok) throw new Error(await brainErrorText(response, 'Search failed.'));
                const payload = await response.json() as { sources?: AttachableSource[] };
                setResults(payload.sources ?? []);
            } catch (error) {
                if (!controller.signal.aborted) setMessage({ tone: 'error', text: error instanceof Error ? error.message : 'Search failed.' });
            } finally {
                if (!controller.signal.aborted) setIsSearching(false);
            }
        }, 220);
        return () => { controller.abort(); window.clearTimeout(timer); };
    }, [open, query, isLink]);

    const attachLink = async () => {
        if (isLinking || full) return;
        setIsLinking(true);
        setMessage(null);
        try {
            const response = await fetch(api('/api/brain/drive/attach'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ link: query.trim() }),
            });
            if (!response.ok) throw new Error(await brainErrorText(response, 'Could not attach that Drive file.'));
            const payload = await response.json() as { status: string; source?: AttachableSource; sourceId: number };
            const source = payload.source ?? { id: payload.sourceId };
            onAdd({ ...source, id: payload.sourceId });
            setMessage({ tone: 'ok', text: payload.status === 'unchanged'
                ? `Already in your library, now attached: ${attachmentLabel(source)}.`
                : `Indexed and attached: ${attachmentLabel(source)}.` });
            setQuery('');
        } catch (error) {
            setMessage({ tone: 'error', text: error instanceof Error ? error.message : 'Could not attach that Drive file.' });
        } finally {
            setIsLinking(false);
        }
    };

    if (!open) return null;
    return (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-3 sm:items-center" onClick={onClose}>
            <div
                role="dialog"
                aria-label="Attach files to this question"
                className="flex max-h-[80vh] w-full max-w-xl flex-col border border-white/[0.12] bg-[#080d08] shadow-2xl"
                onClick={event => event.stopPropagation()}
            >
                <div className="flex items-center gap-2 border-b border-white/[0.08] px-4 py-3">
                    <Paperclip className="h-4 w-4 text-emerald-300" />
                    <h2 className="flex-1 text-xs font-bold uppercase tracking-[0.1em] text-slate-200">Attach to this question</h2>
                    <span className="text-[10px] text-slate-500">{attachedIds.size} / {max}</span>
                    <button type="button" onClick={onClose} className="p-1 text-slate-500 hover:text-slate-200" aria-label="Close"><X className="h-4 w-4" /></button>
                </div>

                <div className="border-b border-white/[0.08] p-3">
                    <label className="flex items-center gap-2 border border-white/[0.12] bg-white/[0.02] px-3 py-2 focus-within:border-emerald-500/40">
                        {isLink ? <Link2 className="h-4 w-4 shrink-0 text-emerald-300" /> : <Search className="h-4 w-4 shrink-0 text-slate-500" />}
                        <input
                            ref={inputRef}
                            value={query}
                            onChange={event => { setQuery(event.target.value); setMessage(null); }}
                            onKeyDown={event => { if (event.key === 'Enter' && isLink) { event.preventDefault(); void attachLink(); } }}
                            placeholder="Search your library, or paste a Google Drive link"
                            aria-label="Search your library, or paste a Google Drive link"
                            className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-600"
                        />
                        {(isSearching || isLinking) && <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-slate-400" />}
                    </label>
                    {isLink && (
                        <button
                            type="button"
                            onClick={() => void attachLink()}
                            disabled={isLinking || full}
                            className="mt-2 w-full border border-emerald-500/35 bg-emerald-500/[0.07] px-3 py-2 text-left text-xs text-emerald-200 hover:bg-emerald-500/[0.12] disabled:opacity-50"
                        >
                            {isLinking ? 'Reading the file from Drive…' : full ? `Remove an attachment first (limit ${max})` : 'Attach this Drive file — it is indexed now if it is not in your library yet'}
                        </button>
                    )}
                    {message && (
                        <p className={cn('mt-2 text-xs leading-5', message.tone === 'ok' ? 'text-emerald-300/90' : 'text-rose-300')}>{message.text}</p>
                    )}
                </div>

                {attached.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 border-b border-white/[0.08] px-3 py-2">
                        {attached.map(source => (
                            <span key={source.id} className="inline-flex max-w-full items-center gap-1 border border-emerald-500/30 bg-emerald-500/[0.06] px-2 py-0.5 text-[11px] text-emerald-200">
                                <FileText className="h-3 w-3 shrink-0" />
                                <span className="truncate">{attachmentLabel(source)}</span>
                                <button type="button" onClick={() => typeof source.id === 'number' && onRemove(source.id)} className="shrink-0 text-emerald-300/70 hover:text-white" aria-label={`Remove ${attachmentLabel(source)}`}><X className="h-3 w-3" /></button>
                            </span>
                        ))}
                    </div>
                )}

                {!isLink && (
                    <ul className="min-h-0 flex-1 overflow-y-auto p-1.5">
                        {!isSearching && results.length === 0 && (
                            <li className="px-3 py-6 text-center text-xs text-slate-500">{query.trim() ? 'Nothing in your library matches. Paste the Drive link to add it.' : 'Your library is empty.'}</li>
                        )}
                        {results.map(source => {
                            const id = typeof source.id === 'number' ? source.id : null;
                            const isOn = id !== null && attachedIds.has(id);
                            const path = String((source.metadata?.relativePath as string | undefined) ?? source.relativePath ?? '');
                            return (
                                <li key={id ?? attachmentLabel(source)}>
                                    <button
                                        type="button"
                                        disabled={id === null || (!isOn && full)}
                                        onClick={() => { if (id === null) return; if (isOn) onRemove(id); else onAdd(source); }}
                                        className={cn('flex w-full items-start gap-2 px-3 py-2 text-left transition-colors disabled:opacity-40',
                                            isOn ? 'bg-emerald-500/[0.08]' : 'hover:bg-white/[0.04]')}
                                    >
                                        <span className={cn('mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center border text-[10px]',
                                            isOn ? 'border-emerald-400 bg-emerald-400/20 text-emerald-200' : 'border-white/20 text-transparent')}>✓</span>
                                        <span className="min-w-0 flex-1">
                                            <span className="block truncate text-sm text-slate-100">{attachmentLabel(source)}</span>
                                            {path && path !== attachmentLabel(source) && <span className="block truncate text-[11px] text-slate-500">{path}</span>}
                                        </span>
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                )}

                <div className="flex items-center justify-between gap-2 border-t border-white/[0.08] px-4 py-2.5 text-[11px] text-slate-500">
                    <span>Read in full for this question only.</span>
                    <button type="button" onClick={onClose} className="border border-white/15 px-3 py-1 text-slate-200 hover:bg-white/[0.06]">Done</button>
                </div>
            </div>
        </div>
    );
};
