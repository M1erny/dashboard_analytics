const DEFAULT_BRAIN_API_URL = 'https://dashboard-eo6k.onrender.com';

export const API_BASE = (
    import.meta.env.VITE_BRAIN_API_URL
    ?? import.meta.env.VITE_API_URL
    ?? DEFAULT_BRAIN_API_URL
).replace(/\/$/, '');

export const api = (path: string) => `${API_BASE}${path}`;

/** Pull the useful part out of a failed Brain response without leaking HTML. */
export const brainErrorText = async (response: Response, fallback: string): Promise<string> => {
    try {
        const payload = await response.json();
        const detail = payload?.detail;
        if (typeof detail === 'string' && detail.trim()) return detail;
        if (detail && typeof detail === 'object') {
            const message = (detail as Record<string, unknown>).message;
            if (typeof message === 'string' && message.trim()) return message;
        }
        if (typeof payload?.message === 'string' && payload.message.trim()) return payload.message;
    } catch {
        // A non-JSON body is normally a proxy or cold-start page, not a useful message.
    }
    return `${fallback} (HTTP ${response.status})`;
};
