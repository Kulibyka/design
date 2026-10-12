-- Все восемь операций варианта 9. Запуск из корня проекта: psql -f postgresql/queries.sql.
-- Это примеры с конкретными значениями; в API значения передаются параметрами psycopg.
-- Демонстрационные изменения откатываются в конце и не остаются в базе.
BEGIN;

-- 1. Создание нового пользователя. Пароль хешируется в Python до INSERT.
INSERT INTO users (id, login, first_name, last_name, password_hash)
VALUES (
    '11111111-1111-4111-8111-111111111111', lower('demo_user'), 'Ivan', 'Petrov',
    '$argon2id$v=19$m=65536,t=3,p=4$cjrweZivnffTJhze9PgvSg$luEiJ2OeKObGJmBAkKnjePH4CycsfgI4pcweBQTL6Ls'
)
RETURNING id, login, first_name, last_name, created_at;

-- 2. Поиск пользователя по логину без учёта регистра.
SELECT id, login, first_name, last_name, created_at
FROM users
WHERE login = lower('DEMO_USER');

-- 3. Поиск по маскам имени и фамилии: Iv* и Pet?ov.
-- API заменяет * на %, ? на _, а исходные %, _ и обратный слеш экранирует.
SELECT id, login, first_name, last_name, created_at
FROM users
WHERE lower(first_name) LIKE 'iv%'
  AND lower(last_name) LIKE 'pet_ov'
ORDER BY login;

-- 4. Создание папки. user_id берётся из сессии текущего пользователя.
INSERT INTO folders (id, user_id, name)
VALUES (
    '22222222-2222-4222-8222-222222222222',
    '11111111-1111-4111-8111-111111111111', 'Study'
)
RETURNING id, user_id, name, created_at;

-- 5. Получение всех папок текущего пользователя.
SELECT id, user_id, name, created_at
FROM folders
WHERE user_id = '11111111-1111-4111-8111-111111111111'
ORDER BY name, id;

-- 6. Создание письма в собственной папке.
INSERT INTO messages (code, folder_id, subject, body, recipient_address)
SELECT '33333333-3333-4333-8333-333333333333', id,
       'Homework', 'Project description.', 'teacher@example.com'
FROM folders
WHERE id = '22222222-2222-4222-8222-222222222222'
  AND user_id = '11111111-1111-4111-8111-111111111111'
RETURNING code, folder_id, subject, body, recipient_address, created_at;

-- 7. Получение всех писем папки с проверкой владельца.
SELECT m.*
FROM messages AS m
JOIN folders AS f ON f.id = m.folder_id
WHERE m.folder_id = '22222222-2222-4222-8222-222222222222'
  AND f.user_id = '11111111-1111-4111-8111-111111111111'
ORDER BY m.created_at, m.code;

-- 8. Получение письма по коду с проверкой владельца.
SELECT m.*
FROM messages AS m
JOIN folders AS f ON f.id = m.folder_id
WHERE m.code = '33333333-3333-4333-8333-333333333333'
  AND f.user_id = '11111111-1111-4111-8111-111111111111';

ROLLBACK;
