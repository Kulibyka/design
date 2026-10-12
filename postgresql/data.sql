-- По 10 записей в каждой таблице. Пароль всех тестовых пользователей: example-password.
-- Ниже хранится его готовый хеш Argon2id, а не открытый пароль.
BEGIN;

INSERT INTO users (id, login, first_name, last_name, password_hash)
SELECT id::UUID, login, first_name, last_name,
       '$argon2id$v=19$m=65536,t=3,p=4$cjrweZivnffTJhze9PgvSg$luEiJ2OeKObGJmBAkKnjePH4CycsfgI4pcweBQTL6Ls'
FROM (VALUES
    ('10000000-0000-4000-8000-000000000001', 'user01', 'Ivan', 'Petrov'),
    ('10000000-0000-4000-8000-000000000002', 'user02', 'Anna', 'Ivanova'),
    ('10000000-0000-4000-8000-000000000003', 'user03', 'Petr', 'Sidorov'),
    ('10000000-0000-4000-8000-000000000004', 'user04', 'Maria', 'Smirnova'),
    ('10000000-0000-4000-8000-000000000005', 'user05', 'Alexey', 'Kuznetsov'),
    ('10000000-0000-4000-8000-000000000006', 'user06', 'Elena', 'Popova'),
    ('10000000-0000-4000-8000-000000000007', 'user07', 'Dmitry', 'Vasilyev'),
    ('10000000-0000-4000-8000-000000000008', 'user08', 'Olga', 'Sokolova'),
    ('10000000-0000-4000-8000-000000000009', 'user09', 'Sergey', 'Mikhailov'),
    ('10000000-0000-4000-8000-000000000010', 'user10', 'Natalia', 'Fedorova')
) AS test_users(id, login, first_name, last_name)
ON CONFLICT DO NOTHING;

INSERT INTO folders (id, user_id, name)
SELECT ('20000000-0000-4000-8000-' || lpad(n::TEXT, 12, '0'))::UUID,
       ('10000000-0000-4000-8000-' || lpad(n::TEXT, 12, '0'))::UUID,
       'Inbox'
FROM generate_series(1, 10) AS n
ON CONFLICT DO NOTHING;

INSERT INTO messages (code, folder_id, subject, body, recipient_address)
SELECT ('30000000-0000-4000-8000-' || lpad(n::TEXT, 12, '0'))::UUID,
       ('20000000-0000-4000-8000-' || lpad(n::TEXT, 12, '0'))::UUID,
       'Test message ' || n,
       'Example message for homework 03.',
       'teacher@example.com'
FROM generate_series(1, 10) AS n
ON CONFLICT DO NOTHING;

COMMIT;
