/** The fields of a library source this picker needs; structurally a SourceReference. */
export type AttachableSource = {
    id?: number;
    title?: string;
    fileName?: string;
    relativePath?: string;
    kind?: string;
    metadata?: Record<string, unknown>;
};

/** A Drive share link, open link, or bare file id. Mirrors drive_indexer.parse_drive_file_id. */
export const looksLikeDriveReference = (value: string): boolean => {
    const text = value.trim();
    if (!text) return false;
    if (/(drive|docs)\.google\.com\//i.test(text)) return true;
    return /^[A-Za-z0-9_-]{25,100}$/.test(text);
};

export const attachmentLabel = (source: AttachableSource): string =>
    source.title || source.fileName || source.relativePath || (source.id ? `Source ${source.id}` : 'Untitled');
