-- Speed up embedding backfills by indexing the small set of chunks that still
-- need vectors.

CREATE INDEX IF NOT EXISTS idx_chunks_missing_embedding_order
ON public.chunks(source_id, ordinal)
WHERE embedding IS NULL;
