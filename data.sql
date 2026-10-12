-- По 10 записей в каждой таблице. Пароль всех тестовых пользователей: example-password.
-- Ниже хранится его готовый хеш Argon2id, а не открытый пароль.
BEGIN;

INSERT INTO users (id, login, first_name, last_name, password_hash)
SELECT id::UUID, login, first_name, last_name,
       '$argon2id$v=19$m=65536,t=3,p=4$cjrweZivnffTJhze9PgvSg$luEiJ2OeKObGJmBAkKnjePH4CycsfgI4pcweBQTL6Ls'
FROM (VALUES
    ('10000000-0000-4000-8000-000000000001', 'user01', 'Иван', 'Петров'),
    ('10000000-0000-4000-8000-000000000002', 'user02', 'Анна', 'Иванова'),
    ('10000000-0000-4000-8000-000000000003', 'user03', 'Пётр', 'Сидоров'),
    ('10000000-0000-4000-8000-000000000004', 'user04', 'Мария', 'Смирнова'),
    ('10000000-0000-4000-8000-000000000005', 'user05', 'Алексей', 'Кузнецов'),
    ('10000000-0000-4000-8000-000000000006', 'user06', 'Елена', 'Попова'),
    ('10000000-0000-4000-8000-000000000007', 'user07', 'Дмитрий', 'Васильев'),
    ('10000000-0000-4000-8000-000000000008', 'user08', 'Ольга', 'Соколова'),
    ('10000000-0000-4000-8000-000000000009', 'user09', 'Сергей', 'Михайлов'),
    ('10000000-0000-4000-8000-000000000010', 'user10', 'Наталья', 'Фёдорова')
) AS test_users(id, login, first_name, last_name)
ON CONFLICT DO NOTHING;

INSERT INTO folders (id, user_id, name)
SELECT ('20000000-0000-4000-8000-' || lpad(n::TEXT, 12, '0'))::UUID,
       ('10000000-0000-4000-8000-' || lpad(n::TEXT, 12, '0'))::UUID,
       'Входящие'
FROM generate_series(1, 10) AS n
ON CONFLICT DO NOTHING;

INSERT INTO messages (code, folder_id, subject, body, recipient_address)
SELECT ('30000000-0000-4000-8000-' || lpad(n::TEXT, 12, '0'))::UUID,
       ('20000000-0000-4000-8000-' || lpad(n::TEXT, 12, '0'))::UUID,
       'Тестовое письмо ' || n,
       'Это пример письма для домашнего задания 03.',
       'teacher@example.com'
FROM generate_series(1, 10) AS n
ON CONFLICT DO NOTHING;

COMMIT;
