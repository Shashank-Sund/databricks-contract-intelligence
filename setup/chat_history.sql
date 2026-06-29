-- Per-user chat history table the app writes each conversation turn into.
-- Create it once (the healthcare example's setup.py creates it for you).
-- Replace <CATALOG>.<SCHEMA> to match your config's uc.catalog / uc.schema.

CREATE TABLE IF NOT EXISTS <CATALOG>.<SCHEMA>.chat_history (
  id              STRING,
  user_email      STRING,
  conversation_id STRING,
  title           STRING,
  role            STRING,     -- 'user' or 'assistant'
  content         STRING,
  turn_id         STRING,
  meta            STRING,     -- JSON blob of tool-result UI payloads
  created_at      TIMESTAMP
) USING DELTA;
