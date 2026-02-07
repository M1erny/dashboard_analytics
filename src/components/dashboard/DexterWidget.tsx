
import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, Loader2, ChevronDown, ChevronUp, AlertCircle } from 'lucide-react';

interface AgentEvent {
    type: string;
    message?: string;
    tool?: string;
    answer?: string;
    args?: any;
    result?: string;
}

interface ChatMessage {
    id: string;
    sender: 'user' | 'agent';
    text: string;
    events?: AgentEvent[];
    error?: string;
}

export const DexterWidget: React.FC = () => {
    const [isOpen, setIsOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set());
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, isLoading]);

    const toggleEvents = (msgId: string) => {
        const newSet = new Set(expandedEvents);
        if (newSet.has(msgId)) {
            newSet.delete(msgId);
        } else {
            newSet.add(msgId);
        }
        setExpandedEvents(newSet);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!query.trim() || isLoading) return;

        const userMsg: ChatMessage = {
            id: Date.now().toString(),
            sender: 'user',
            text: query
        };

        setMessages(prev => [...prev, userMsg]);
        setQuery('');
        setIsLoading(true);

        try {
            // Call Dexter API
            const response = await fetch('http://localhost:3001/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: userMsg.text })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to get response');
            }

            const agentMsg: ChatMessage = {
                id: (Date.now() + 1).toString(),
                sender: 'agent',
                text: data.answer || "I processed your request but didn't generate a text answer.",
                events: data.events
            };

            setMessages(prev => [...prev, agentMsg]);
        } catch (err: any) {
            const errorMsg: ChatMessage = {
                id: (Date.now() + 1).toString(),
                sender: 'agent',
                text: "Sorry, I encountered an error processing your request.",
                error: err.message
            };
            setMessages(prev => [...prev, errorMsg]);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className={`fixed bottom-4 right-4 z-50 transition-all duration-300 ${isOpen ? 'w-96 h-[600px]' : 'w-auto h-auto'}`}>
            {!isOpen && (
                <button
                    onClick={() => setIsOpen(true)}
                    className="bg-emerald-600 hover:bg-emerald-500 text-white p-4 rounded-full shadow-lg flex items-center gap-2 transition-all"
                >
                    <Bot size={24} />
                    <span className="font-semibold">Ask Dexter</span>
                </button>
            )}

            {isOpen && (
                <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full h-full flex flex-col overflow-hidden">
                    {/* Header */}
                    <div className="bg-slate-800 p-3 flex justify-between items-center border-b border-slate-700">
                        <div className="flex items-center gap-2">
                            <Bot className="text-emerald-400" size={20} />
                            <span className="font-semibold text-white">Dexter Financial Agent</span>
                        </div>
                        <button
                            onClick={() => setIsOpen(false)}
                            className="text-slate-400 hover:text-white"
                        >
                            <ChevronDown size={20} />
                        </button>
                    </div>

                    {/* Chat Area */}
                    <div className="flex-1 overflow-y-auto p-4 space-y-4">
                        {messages.length === 0 && (
                            <div className="text-center text-slate-500 mt-10">
                                <Bot size={48} className="mx-auto mb-2 opacity-50" />
                                <p>How can I help with your financial research today?</p>
                            </div>
                        )}

                        {messages.map((msg) => (
                            <div key={msg.id} className={`flex flex-col ${msg.sender === 'user' ? 'items-end' : 'items-start'}`}>
                                <div className={`max-w-[85%] rounded-lg p-3 ${msg.sender === 'user'
                                        ? 'bg-emerald-600 text-white'
                                        : msg.error
                                            ? 'bg-red-900/50 border border-red-700 text-red-200'
                                            : 'bg-slate-800 text-slate-200'
                                    }`}>
                                    <p className="whitespace-pre-wrap text-sm">{msg.text}</p>

                                    {msg.error && (
                                        <div className="flex items-center gap-1 mt-2 text-xs text-red-400">
                                            <AlertCircle size={12} />
                                            <span>{msg.error}</span>
                                        </div>
                                    )}
                                </div>

                                {/* Agent Events / Thinking Process */}
                                {msg.sender === 'agent' && msg.events && msg.events.length > 0 && (
                                    <div className="mt-1 max-w-[85%] w-full">
                                        <button
                                            onClick={() => toggleEvents(msg.id)}
                                            className="text-xs text-slate-500 hover:text-emerald-400 flex items-center gap-1 mb-1 transition-colors"
                                        >
                                            {expandedEvents.has(msg.id) ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                                            {expandedEvents.has(msg.id) ? 'Hide Process' : `Show Process (${msg.events.length} steps)`}
                                        </button>

                                        {expandedEvents.has(msg.id) && (
                                            <div className="bg-slate-950/50 rounded-lg p-2 text-xs font-mono border border-slate-800 space-y-2 overflow-x-auto">
                                                {msg.events.map((evt, idx) => (
                                                    <div key={idx} className="border-b border-slate-800/50 pb-2 last:border-0 last:pb-0">
                                                        <div className="flex items-center gap-2 mb-1">
                                                            <span className={`uppercase font-bold text-[10px] px-1.5 py-0.5 rounded ${evt.type === 'thinking' ? 'bg-blue-900/30 text-blue-400' :
                                                                    evt.type === 'tool_start' ? 'bg-purple-900/30 text-purple-400' :
                                                                        evt.type === 'tool_end' ? 'bg-green-900/30 text-green-400' :
                                                                            'bg-slate-800 text-slate-400'
                                                                }`}>
                                                                {evt.type}
                                                            </span>
                                                            {evt.tool && <span className="text-slate-300 font-semibold">{evt.tool}</span>}
                                                        </div>

                                                        {evt.message && <p className="text-slate-400 pl-2 border-l-2 border-slate-800">{evt.message}</p>}
                                                        {evt.args && (
                                                            <pre className="text-slate-500 overflow-x-auto pl-2">{JSON.stringify(evt.args, null, 2)}</pre>
                                                        )}
                                                        {evt.result && (
                                                            <details>
                                                                <summary className="cursor-pointer text-slate-500 hover:text-slate-300">Result Output</summary>
                                                                <pre className="text-slate-600 mt-1 max-h-32 overflow-y-auto">{evt.result}</pre>
                                                            </details>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        ))}

                        {isLoading && (
                            <div className="flex items-start gap-2">
                                <div className="bg-slate-800 rounded-lg p-3 flex items-center gap-2">
                                    <Loader2 className="animate-spin text-emerald-400" size={16} />
                                    <span className="text-sm text-slate-400">Dexter is thinking...</span>
                                </div>
                            </div>
                        )}
                        <div ref={messagesEndRef} />
                    </div>

                    {/* Input Area */}
                    <form onSubmit={handleSubmit} className="p-3 bg-slate-800 border-t border-slate-700">
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                placeholder="Ask about stocks, analysis, or market data..."
                                className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 text-sm"
                                disabled={isLoading}
                            />
                            <button
                                type="submit"
                                disabled={isLoading || !query.trim()}
                                className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white p-2 rounded-lg transition-colors"
                            >
                                <Send size={18} />
                            </button>
                        </div>
                    </form>
                </div>
            )}
        </div>
    );
};
