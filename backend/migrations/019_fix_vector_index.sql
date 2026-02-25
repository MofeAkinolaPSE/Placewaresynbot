-- Fix for generic answers: valid data is hidden by a broken index
-- Run this in your Supabase SQL Editor

DROP INDEX IF EXISTS public.idx_qna_embedding_ivfflat;

-- If you want to recreate it later (only needed for >10k rows):
-- CREATE INDEX idx_qna_embedding_ivfflat ON public.qna USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
