-- PostgreSQL 16. Схема для варианта 9 «Электронная почта».

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL CHECK (length(btrim(first_name)) > 0),
    last_name TEXT NOT NULL CHECK (length(btrim(last_name)) > 0),
    password_hash TEXT NOT NULL CHECK (length(password_hash) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (length(login) > 0 AND login = lower(btrim(login)))
);

CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    name TEXT NOT NULL CHECK (length(btrim(name)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS messages (
    code UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    folder_id UUID NOT NULL REFERENCES folders(id),
    subject TEXT NOT NULL CHECK (length(btrim(subject)) > 0),
    body TEXT NOT NULL CHECK (length(btrim(body)) > 0),
    recipient_address TEXT NOT NULL CHECK (
        recipient_address ~ '^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Индексы PK и UNIQUE PostgreSQL создаёт автоматически.
-- UNIQUE (user_id, name) также покрывает FK folders.user_id и поиск папок владельца.

-- Поиск по маске с известным началом строки: lower(first_name) LIKE 'ivan%'.
CREATE INDEX IF NOT EXISTS idx_users_first_name
    ON users (lower(first_name) text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_users_last_name
    ON users (lower(last_name) text_pattern_ops);

-- Покрывает FK, WHERE folder_id и ORDER BY created_at, code при чтении писем.
CREATE INDEX IF NOT EXISTS idx_messages_folder_created
    ON messages (folder_id, created_at, code);
