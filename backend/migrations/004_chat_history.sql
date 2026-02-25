-- Chat history table for storing Q&A with sources

create table if not exists placeware_chat_history (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  user_id text,
  question text not null,
  answer text not null,
  sources jsonb not null default '[]'::jsonb
);

create index if not exists idx_chat_history_user_created on placeware_chat_history (user_id, created_at desc);
-- Chat history table to persist Q&A and sources per user

create table if not exists placeware_chat_history (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  user_id text,
  question text not null,
  answer text not null,
  sources jsonb
);
