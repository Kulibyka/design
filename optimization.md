# Оптимизация запросов — домашнее задание 03

## Индексы и частые запросы

| Индекс | Назначение |
| --- | --- |
| `users_pkey` | PK пользователя; связь `folders.user_id → users.id` |
| `users_login_key` | UNIQUE логина; регистрация, поиск по логину и вход |
| `folders_pkey` | PK папки; проверка доступа и JOIN с письмами |
| `folders_user_id_name_key` | UNIQUE имени папки у владельца; покрывает FK `user_id`, WHERE владельца и начало сортировки по имени |
| `messages_pkey` | PK кода письма; получение одного письма |
| `idx_users_first_name` | `lower(first_name) text_pattern_ops`: поиск без учёта регистра по началу имени |
| `idx_users_last_name` | `lower(last_name) text_pattern_ops`: такой же поиск по фамилии, в том числе без маски имени |
| `idx_messages_folder_created` | `(folder_id, created_at, code)`: FK папки, выборка писем папки, возможность чтения в нужном порядке |

Первые пять индексов автоматически создаются ограничениями PK и UNIQUE.
Остальные три явно создаются в `schema.sql`. Все индексы — B-tree.
Составной UNIQUE папки уже начинается с `user_id` и покрывает этот внешний ключ.
Связи в JOIN используют `folders.id` и `messages.folder_id`.

Логин нормализуется перед INSERT и поиском, поэтому запрос использует `login = %s`,
а не `lower(login) = %s`; подходит обычный индекс UNIQUE. Для масок API экранирует
исходные `%`, `_` и обратный слеш, затем заменяет `*` на `%`, а `?` на `_`.
Условие `lower(first_name) LIKE 'иван%'` соответствует выражению индекса.
`text_pattern_ops` позволяет использовать известное начало строки при LIKE.
Маска с начальным `*` и поиск всех пользователей могут потребовать полного просмотра.

Запрос поиска возвращает только публичные колонки пользователя. Создание папки
и письма и чтение сообщений проверяют владельца. Значения во всех запросах API
передаются параметрами psycopg. Все восемь операций приведены в `queries.sql`.

## Условия измерения

Планы получены на PostgreSQL 16.15 в Docker, в отдельной базе `maildb_optimization`.
В каждой таблице было 50 000 строк: 10 записей из `data.sql` и 49 990 нагрузочных.
Поиск возвращал 51 пользователя, выбранная папка содержала 51 письмо.
На десяти строках планировщик может предпочесть Seq Scan, поэтому для сравнения
использована более крупная выборка. Рабочая `maildb` не менялась.

До оптимизации сохранены только автоматические индексы PK и UNIQUE.
После добавлены три индекса из `schema.sql`. Перед обеими сериями выполнен ANALYZE;
перед каждым EXPLAIN запрос выполнен один раз для прогрева. Использовался
`EXPLAIN (ANALYZE, BUFFERS)`, настройки планировщика не изменялись.
Ниже приведён фактический вывод одного сравнительного запуска.

| Запрос | До, мс | После, мс |
| --- | ---: | ---: |
| Поиск по двум маскам | 9.397 | 0.097 |
| Письма папки с проверкой владельца | 2.370 | 0.119 |
| Поиск по логину | 0.017 | 0.019 |
| Папки пользователя | 0.052 | 0.024 |
| Письмо по коду с проверкой владельца | 0.028 | 0.027 |

Два первых запроса стали читать небольшую часть таблицы вместо всех 50 000 строк.
Остальные уже использовали индексы PK/UNIQUE; различия их времени в этом запуске
слишком малы, чтобы считать их отдельным результатом оптимизации. Время зависит
от машины, распределения данных и кеша.

## Поиск по маскам

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, login, first_name, last_name, created_at FROM users
WHERE lower(first_name) LIKE 'иван%' AND lower(last_name) LIKE 'петров%'
ORDER BY login;
```

### До

```text
Sort  (cost=2219.01..2219.02 rows=1 width=65) (actual time=9.377..9.380 rows=51 loops=1)
  Sort Key: login
  Sort Method: quicksort  Memory: 29kB
  Buffers: shared hit=1219
  ->  Seq Scan on users  (cost=0.00..2219.00 rows=1 width=65) (actual time=0.008..9.340 rows=51 loops=1)
        Filter: ((lower(first_name) ~~ 'иван%'::text) AND (lower(last_name) ~~ 'петров%'::text))
        Rows Removed by Filter: 49949
        Buffers: shared hit=1219
Planning Time: 0.067 ms
Execution Time: 9.397 ms
```

### После

```text
Sort  (cost=8.33..8.33 rows=1 width=65) (actual time=0.083..0.085 rows=51 loops=1)
  Sort Key: login
  Sort Method: quicksort  Memory: 29kB
  Buffers: shared hit=53
  ->  Index Scan using idx_users_first_name on users  (cost=0.29..8.32 rows=1 width=65) (actual time=0.012..0.047 rows=51 loops=1)
        Index Cond: ((lower(first_name) ~>=~ 'иван'::text) AND (lower(first_name) ~<~ 'ивао'::text))
        Filter: ((lower(first_name) ~~ 'иван%'::text) AND (lower(last_name) ~~ 'петров%'::text))
        Buffers: shared hit=53
Planning Time: 0.064 ms
Execution Time: 0.097 ms
```

Вместо Seq Scan используется `idx_users_first_name`. Число обращений к буферам
уменьшилось с 1219 до 53. Проверка фамилии осталась фильтром; PostgreSQL выбрал
один из двух индексов как более подходящий для этой выборки.

## Получение писем папки

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT m.* FROM messages AS m
JOIN folders AS f ON f.id = m.folder_id
WHERE m.folder_id = '20000000-0000-4000-8000-000000000001'
  AND f.user_id = '10000000-0000-4000-8000-000000000001'
ORDER BY m.created_at, m.code;
```

### До

```text
Sort  (cost=1489.36..1489.49 rows=53 width=103) (actual time=2.344..2.346 rows=51 loops=1)
  Sort Key: m.created_at, m.code
  Sort Method: quicksort  Memory: 31kB
  Buffers: shared hit=857
  ->  Nested Loop  (cost=0.29..1487.84 rows=53 width=103) (actual time=0.012..2.325 rows=51 loops=1)
        Buffers: shared hit=857
        ->  Index Scan using folders_pkey on folders f  (cost=0.29..8.31 rows=1 width=16) (actual time=0.009..0.010 rows=1 loops=1)
              Index Cond: (id = '20000000-0000-4000-8000-000000000001'::uuid)
              Filter: (user_id = '10000000-0000-4000-8000-000000000001'::uuid)
              Buffers: shared hit=3
        ->  Seq Scan on messages m  (cost=0.00..1479.00 rows=53 width=103) (actual time=0.002..2.307 rows=51 loops=1)
              Filter: (folder_id = '20000000-0000-4000-8000-000000000001'::uuid)
              Rows Removed by Filter: 49949
              Buffers: shared hit=854
Planning Time: 0.047 ms
Execution Time: 2.370 ms
```

### После

```text
Sort  (cost=197.09..197.23 rows=57 width=103) (actual time=0.086..0.088 rows=51 loops=1)
  Sort Key: m.created_at, m.code
  Sort Method: quicksort  Memory: 31kB
  Buffers: shared hit=58
  ->  Nested Loop  (cost=5.15..195.43 rows=57 width=103) (actual time=0.020..0.070 rows=51 loops=1)
        Buffers: shared hit=58
        ->  Index Scan using folders_pkey on folders f  (cost=0.29..8.31 rows=1 width=16) (actual time=0.007..0.008 rows=1 loops=1)
              Index Cond: (id = '20000000-0000-4000-8000-000000000001'::uuid)
              Filter: (user_id = '10000000-0000-4000-8000-000000000001'::uuid)
              Buffers: shared hit=3
        ->  Bitmap Heap Scan on messages m  (cost=4.86..186.55 rows=57 width=103) (actual time=0.011..0.056 rows=51 loops=1)
              Recheck Cond: (folder_id = '20000000-0000-4000-8000-000000000001'::uuid)
              Heap Blocks: exact=51
              Buffers: shared hit=55
              ->  Bitmap Index Scan on idx_messages_folder_created  (cost=0.00..4.84 rows=57 width=0) (actual time=0.008..0.008 rows=51 loops=1)
                    Index Cond: (folder_id = '20000000-0000-4000-8000-000000000001'::uuid)
                    Buffers: shared hit=4
Planning Time: 0.050 ms
Execution Time: 0.119 ms
```

Вместо Seq Scan писем используются Bitmap Index Scan и Bitmap Heap Scan.
Число обращений к буферам уменьшилось с 857 до 58. Проверка владельца папки
по-прежнему выполняется. Sort остался: выбранный Bitmap Scan не сохраняет порядок
составного индекса. Индекс допускает и обычное упорядоченное чтение, но конкретный
план выбирает PostgreSQL по стоимости.

## Остальные SELECT-запросы

### Поиск по логину

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM users WHERE login = 'user01';
```

План после добавления индексов:

```text
Index Scan using users_login_key on users  (cost=0.41..8.43 rows=1 width=163) (actual time=0.010..0.011 rows=1 loops=1)
  Index Cond: (login = 'user01'::text)
  Buffers: shared hit=4
Planning Time: 0.018 ms
Execution Time: 0.019 ms
```

### Папки пользователя

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM folders
WHERE user_id = '10000000-0000-4000-8000-000000000001' ORDER BY name, id;
```

План после добавления индексов:

```text
Incremental Sort  (cost=8.44..8.49 rows=2 width=57) (actual time=0.013..0.013 rows=1 loops=1)
  Sort Key: name, id
  Presorted Key: name
  Full-sort Groups: 1  Sort Method: quicksort  Average Memory: 25kB  Peak Memory: 25kB
  Buffers: shared hit=4
  ->  Index Scan using folders_user_id_name_key on folders  (cost=0.41..8.43 rows=1 width=57) (actual time=0.006..0.007 rows=1 loops=1)
        Index Cond: (user_id = '10000000-0000-4000-8000-000000000001'::uuid)
        Buffers: shared hit=4
Planning Time: 0.021 ms
Execution Time: 0.024 ms
```

### Письмо по коду с проверкой владельца

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT m.* FROM messages AS m
JOIN folders AS f ON f.id = m.folder_id
WHERE m.code = '30000000-0000-4000-8000-000000000001'
  AND f.user_id = '10000000-0000-4000-8000-000000000001';
```

План после добавления индексов:

```text
Nested Loop  (cost=0.70..16.75 rows=1 width=103) (actual time=0.015..0.016 rows=1 loops=1)
  Join Filter: (m.folder_id = f.id)
  Buffers: shared hit=7
  ->  Index Scan using messages_pkey on messages m  (cost=0.29..8.31 rows=1 width=103) (actual time=0.009..0.009 rows=1 loops=1)
        Index Cond: (code = '30000000-0000-4000-8000-000000000001'::uuid)
        Buffers: shared hit=3
  ->  Index Scan using folders_user_id_name_key on folders f  (cost=0.41..8.43 rows=1 width=16) (actual time=0.004..0.004 rows=1 loops=1)
        Index Cond: (user_id = '10000000-0000-4000-8000-000000000001'::uuid)
        Buffers: shared hit=4
Planning:
  Buffers: shared hit=14
Planning Time: 0.100 ms
Execution Time: 0.027 ms
```

INSERT-запросы из `queries.sql` используют ограничения PK, FK, UNIQUE и CHECK.
Добавленные индексы ускоряют чтение, но требуют дополнительного места и обновления
при INSERT. Индексы выбраны для существующих операций API.

## Как повторить сравнение

Создать отдельную базу один раз и загрузить исходные файлы:

```bash
docker compose exec db createdb -U mail maildb_optimization
docker compose exec -T db psql -U mail -d maildb_optimization -v ON_ERROR_STOP=1 < schema.sql
docker compose exec -T db psql -U mail -d maildb_optimization -v ON_ERROR_STOP=1 < data.sql
docker compose exec db psql -U mail -d maildb_optimization
```

В открытом psql выполнить следующий блок. Он предназначен для отдельной
`maildb_optimization`, где пока есть только 10 записей на таблицу:

```sql
BEGIN;
DROP INDEX idx_users_first_name, idx_users_last_name, idx_messages_folder_created;

INSERT INTO users (id, login, first_name, last_name, password_hash)
SELECT md5('user-' || n)::UUID, 'bench_' || n,
       CASE WHEN n % 1000 = 0 THEN 'Иван' || n ELSE 'Имя' || n END,
       CASE WHEN n % 1000 = 0 THEN 'Петров' || n ELSE 'Фамилия' || n END,
       (SELECT password_hash FROM users WHERE login = 'user01')
FROM generate_series(11, 50000) AS n;

INSERT INTO folders (id, user_id, name)
SELECT md5('folder-' || n)::UUID, md5('user-' || n)::UUID, 'Входящие'
FROM generate_series(11, 50000) AS n;

INSERT INTO messages (code, folder_id, subject, body, recipient_address, created_at)
SELECT md5('message-' || n)::UUID,
       CASE WHEN n % 1000 = 0 THEN '20000000-0000-4000-8000-000000000001'::UUID
            ELSE md5('folder-' || n)::UUID END,
       'Тема ' || n, 'Текст письма ' || n, 'teacher@example.com',
       TIMESTAMPTZ '2026-10-12 12:00:00+00' + n * INTERVAL '1 second'
FROM generate_series(11, 50000) AS n;

ANALYZE users;
ANALYZE folders;
ANALYZE messages;
-- Здесь выполнить SELECT-запросы выше один раз без EXPLAIN для прогрева,
-- затем с EXPLAIN (ANALYZE, BUFFERS): получится серия «до».

CREATE INDEX idx_users_first_name ON users (lower(first_name) text_pattern_ops);
CREATE INDEX idx_users_last_name ON users (lower(last_name) text_pattern_ops);
CREATE INDEX idx_messages_folder_created ON messages (folder_id, created_at, code);
ANALYZE users;
ANALYZE folders;
ANALYZE messages;
-- Повторить такой же прогрев и EXPLAIN: получится серия «после».

ROLLBACK;
```

ROLLBACK удаляет нагрузочные записи и восстанавливает исходные индексы.
Партиционирование — опциональная часть задания; для этой учебной базы оно не применяется.
