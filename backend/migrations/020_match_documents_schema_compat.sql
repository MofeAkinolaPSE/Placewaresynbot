-- Ensure match_documents works across qna id/Id casing drift

create or replace function public.match_documents(
  query_embedding vector(384),
  match_threshold float,
  match_count int
)
returns table (
  id bigint,
  question text,
  answer text,
  similarity float
)
language plpgsql
stable
as $$
declare
  col_id text;
  col_question text;
  col_answer text;
  col_embedding text;
  col_embedding_type text;
  embedding_expr text;
  dyn_sql text;
begin
  select a.attname into col_id
  from pg_attribute a
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'id'
  limit 1;

  select a.attname into col_question
  from pg_attribute a
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'question'
  limit 1;

  select a.attname into col_answer
  from pg_attribute a
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'answer'
  limit 1;

  select a.attname into col_embedding
  from pg_attribute a
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'embedding'
  limit 1;

  select t.typname into col_embedding_type
  from pg_attribute a
  join pg_type t on t.oid = a.atttypid
  where a.attrelid = 'public.qna'::regclass
    and a.attnum > 0
    and not a.attisdropped
    and lower(a.attname) = 'embedding'
  limit 1;

  if col_question is null or col_answer is null or col_embedding is null then
    raise exception 'qna table missing required columns (question/answer/embedding)';
  end if;

  if col_embedding_type = 'vector' then
    embedding_expr := format('q.%I', col_embedding);
  else
    -- Compatibility path for legacy schemas where embedding was stored as json/jsonb/text.
    -- pgvector accepts a text literal like '[0.1,0.2,...]'.
    embedding_expr := format('(q.%I::text)::vector(384)', col_embedding);
  end if;

  dyn_sql := format(
    'select %s as id, q.%I::text as question, q.%I::text as answer, 1 - ((%s) <=> $1) as similarity
       from public.qna q
      where 1 - ((%s) <=> $1) > $2
      order by (%s) <=> $1
      limit $3',
    case when col_id is not null then format('q.%I::bigint', col_id) else 'null::bigint' end,
    col_question,
    col_answer,
    embedding_expr,
    embedding_expr,
    embedding_expr
  );

  return query execute dyn_sql using query_embedding, match_threshold, match_count;
end;
$$;
