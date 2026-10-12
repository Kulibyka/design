# Домашнее задание 04. MongoDB для сервиса электронной почты

Вариант 9. Приложение содержит пользователей, почтовые папки и сообщения.
Реализованы все восемь операций варианта и вход пользователя.

Используются Python 3.12, FastAPI, Pydantic, MongoDB 7 и простой драйвер PyMongo.
Все три сущности теперь хранятся в MongoDB. Пути API и форматы запросов и ответов
из домашней работы 02 сохранены.

## Запуск API и MongoDB через Docker

Из папки проекта, где находится `docker-compose.yaml`:

```bash
docker compose up --build
```

Запускаются сервисы `api` и `mongo`. API слушает порт 8000, MongoDB — 27017.
API ждёт готовности MongoDB. При первом запуске в пустом MongoDB volume
автоматически выполняются `mongodb/validation.js` и `mongodb/data.js`: создаются база `maildb`,
коллекции, валидаторы, индексы и по 10 документов в каждой коллекции.

Можно войти под логином `user01` с паролем `example-password`.
У пользователя уже есть папка «Inbox» и одно письмо.

Swagger UI доступен по пути `/docs`, спецификация — `/openapi.json`.
В Swagger можно зарегистрироваться, выполнить вход и вставить `access_token`
в окно **Authorize**.

Остановка сохраняет данные в volume `mongodb_data`:

```bash
docker compose down
```

Инициализация выполняется только при первом запуске пустого volume.
Применить скрипты вручную или повторно можно так:

```bash
docker compose exec -T mongo mongosh --quiet maildb --file /docker-entrypoint-initdb.d/01-validation.js
docker compose exec -T mongo mongosh --quiet maildb --file /docker-entrypoint-initdb.d/02-data.js
```

Повторная загрузка данных использует `$setOnInsert`, поэтому документы не дублируются
и существующие записи не заменяются.

## Запуск API из Python

MongoDB остаётся в Docker:

```bash
docker compose up -d mongo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB="maildb"
uvicorn main:app --reload
```

В cmd.exe активация и переменные задаются так:

```cmd
.venv\Scripts\activate
set "MONGO_URI=mongodb://localhost:27017"
set "MONGO_DB=maildb"
```

Это же подключение используется Python по умолчанию. В контейнере API имя
сервера в `MONGO_URI` — `mongo`. Для другого сервера задайте переменную перед
запуском Python и примените `mongodb/validation.js` к выбранной базе.

## Коллекции MongoDB

| Коллекция | Состав документа |
| --- | --- |
| `users` | `_id`, `login`, `first_name`, `last_name`, `password_hash`, `created_at` |
| `folders` | `_id`, `user_id`, `name`, `created_at` |
| `messages` | `_id`, `folder_id`, `content: {subject, body}`, `recipients`, `size_bytes`, `created_at` |

UUID хранятся как String, даты — Date, содержимое письма — вложенный Object,
адрес получателя — Array из одной строки, размер текста в UTF-8 — Number.
`user_id` ссылается на пользователя, `folder_id` — на папку.
Обоснование embedded/references и примеры документов находятся в `mongodb/schema_design.md`.

В `mongodb/validation.js` заданы `$jsonSchema`, обязательные поля, BSON-типы,
ограничения строк, массива и числа. Скрипт создаёт уникальные индексы логина
и имени папки у владельца, а также индекс чтения писем папки.

## Выполнение MongoDB-запросов

Открыть интерактивный mongosh:

```bash
docker compose exec mongo mongosh maildb
```

Выполнить `mongodb/queries.js`:

```bash
docker compose exec -T mongo mongosh --quiet maildb --file /scripts/queries.js
```

Скрипт выполняет все восемь операций варианта, примеры Update и Delete для
трёх коллекций и фильтрацию с `$eq`, `$ne`, `$gt`, `$lt`, `$in`, `$and`, `$or`.
Он обновляет и удаляет только свои демонстрационные документы. Завершение
`All variant operations, filters, updates and deletes passed` означает, что
проверки скрипта прошли.

Обновление и удаление представлены запросами MongoDB из задания 04.
HTTP API сохраняет набор операций выбранного варианта.
Необязательные агрегации не используются.

## Материалы предыдущего задания

`postgresql/schema.sql`, `postgresql/data.sql`, `postgresql/queries.sql`, `postgresql/optimization.md` сохранены для работы 03.
PostgreSQL остаётся отдельным сервисом в профиле `postgres`:

```bash
docker compose --profile postgres up -d db
```

Его база и volume сохраняются отдельно. Перенос данных между PostgreSQL и MongoDB
не выполняется: текущий API использует MongoDB. Версия API с PostgreSQL доступна
в [коммите домашней работы 03](https://github.com/Kulibyka/design/tree/43ef16a8cf532726017502b0661290f21dc2a86d).

## Данные и правила

| Сущность | Поля ответа |
| --- | --- |
| Пользователь | `id`, `login`, `first_name`, `last_name`, `created_at` |
| Почтовая папка | `id`, `user_id`, `name`, `created_at` |
| Письмо | `code`, `folder_id`, `subject`, `body`, `recipient_address`, `created_at` |

Идентификаторы и код письма — UUID; дата создания — строка ISO 8601 в UTC.
Логин уникален без учёта регистра и сохраняется в нижнем регистре.
Имя папки уникально в пределах одного пользователя, с учётом регистра.

Логин, имя, фамилия, пароль, название папки, тема и текст письма не должны быть
пустыми. У текстовых полей, кроме пароля, удаляются пробелы по краям.
Адрес получателя проверяется как адрес электронной почты. Неизвестные поля
в теле запроса отклоняются. Владелец папки определяется по токену,
а код письма генерирует сервер.

Пароли хранятся в виде хеша Argon2id и не возвращаются в ответах. После входа
сервер выдаёт случайный сессионный токен на один час. Middleware проверяет
заголовок `Authorization: Bearer <токен>` у всех операций, кроме регистрации
и входа. Это session-based аутентификация, разрешённая заданием.

Каждый пользователь видит только свои папки и письма. Чужие и отсутствующие
папки или письма дают одинаковый статус `404`. Поиск пользователей возвращает
только публичные поля пользователя.

## Endpoints

Все пути начинаются с `/api/v1`.

| Метод и путь | Запрос | Успешный ответ | Токен |
| --- | --- | --- | --- |
| `POST /users` | JSON: `login`, `first_name`, `last_name`, `password` | `201`, пользователь | Нет |
| `POST /auth/login` | JSON: `login`, `password` | `200`, `access_token`, `token_type`, `expires_in` | Нет |
| `GET /users/by-login` | Query: `login` | `200`, пользователь | Да |
| `GET /users` | Query: `first_name_mask` и/или `last_name_mask` | `200`, список пользователей | Да |
| `POST /folders` | JSON: `name` | `201`, папка | Да |
| `GET /folders` | Без тела | `200`, список своих папок | Да |
| `POST /folders/{folder_id}/messages` | UUID папки; JSON: `subject`, `body`, `recipient_address` | `201`, письмо | Да |
| `GET /folders/{folder_id}/messages` | UUID папки | `200`, список писем папки | Да |
| `GET /messages/{code}` | UUID письма | `200`, письмо | Да |

В маске `*` означает любое число символов, `?` — один символ. Остальные символы
считаются обычными. Поиск без учёта регистра; при двух масках должны совпасть
и имя, и фамилия. Нужна хотя бы одна непустая маска.

Если ничего не найдено или папка пуста, возвращается `[]` со статусом `200`.
Пользователи сортируются по логину, папки — по имени и UUID,
письма — по дате создания и коду.

## Примеры запросов и ответов

Команды ниже предназначены для Bash. UUID в ответах — примеры;
для следующих запросов используйте значения, полученные от своего сервера.

### Регистрация

```bash
curl -i -X POST http://localhost:8000/api/v1/users \
  -H 'Content-Type: application/json' \
  -d '{"login":"ivan","first_name":"Ivan","last_name":"Petrov","password":"example-password"}'
```

Ответ `201 Created`:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "login": "ivan",
  "first_name": "Ivan",
  "last_name": "Petrov",
  "created_at": "2026-10-12T12:00:00Z"
}
```

### Вход

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login":"ivan","password":"example-password"}'
```

Ответ `200 OK`:

```json
{"access_token":"example-session-token","token_type":"bearer","expires_in":3600}
```

Сохраните полученный токен в переменную:

```bash
TOKEN='PASTE_ACCESS_TOKEN_HERE'
```

### Поиск пользователя по логину

```bash
curl --get http://localhost:8000/api/v1/users/by-login \
  -H "Authorization: Bearer $TOKEN" --data-urlencode 'login=ivan'
```

Ответ `200 OK` — объект пользователя, как в ответе регистрации.

### Поиск по маске

```bash
curl --get http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'first_name_mask=Iv*' --data-urlencode 'last_name_mask=Pet?ov'
```

Ответ `200 OK` — массив объектов пользователя:

```json
[{"id":"11111111-1111-4111-8111-111111111111","login":"ivan","first_name":"Ivan","last_name":"Petrov","created_at":"2026-10-12T12:00:00Z"}]
```

### Создание папки

```bash
curl -i -X POST http://localhost:8000/api/v1/folders \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Study"}'
```

Ответ `201 Created`:

```json
{"id":"22222222-2222-4222-8222-222222222222","user_id":"11111111-1111-4111-8111-111111111111","name":"Study","created_at":"2026-10-12T12:00:00Z"}
```

### Список папок

```bash
curl http://localhost:8000/api/v1/folders -H "Authorization: Bearer $TOKEN"
```

Ответ `200 OK` — массив папок:

```json
[{"id":"22222222-2222-4222-8222-222222222222","user_id":"11111111-1111-4111-8111-111111111111","name":"Study","created_at":"2026-10-12T12:00:00Z"}]
```

### Создание письма в папке

```bash
FOLDER_ID='PASTE_FOLDER_ID_HERE'
curl -i -X POST "http://localhost:8000/api/v1/folders/$FOLDER_ID/messages" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"subject":"Homework","body":"Project description.","recipient_address":"teacher@example.com"}'
```

Ответ `201 Created`:

```json
{"code":"33333333-3333-4333-8333-333333333333","folder_id":"22222222-2222-4222-8222-222222222222","subject":"Homework","body":"Project description.","recipient_address":"teacher@example.com","created_at":"2026-10-12T12:00:00Z"}
```

### Список писем папки

```bash
curl "http://localhost:8000/api/v1/folders/$FOLDER_ID/messages" -H "Authorization: Bearer $TOKEN"
```

Ответ `200 OK` — массив писем, например:

```json
[{"code":"33333333-3333-4333-8333-333333333333","folder_id":"22222222-2222-4222-8222-222222222222","subject":"Homework","body":"Project description.","recipient_address":"teacher@example.com","created_at":"2026-10-12T12:00:00Z"}]
```

### Получение письма по коду

```bash
CODE='PASTE_MESSAGE_CODE_HERE'
curl "http://localhost:8000/api/v1/messages/$CODE" -H "Authorization: Bearer $TOKEN"
```

Ответ `200 OK` — объект письма, как в ответе создания письма.

## Ошибки

| Статус | Когда возвращается |
| --- | --- |
| `400 Bad Request` | Неправильный JSON, пустые или пропущенные поля, неверный адрес получателя, неверный UUID, отсутствие масок поиска |
| `401 Unauthorized` | Нет токена, токен неверен или истёк; неправильный логин или пароль |
| `404 Not Found` | Пользователь не найден; папка или письмо отсутствует либо принадлежит другому пользователю |
| `409 Conflict` | Логин занят или папка с таким именем уже существует у пользователя |

Формат ошибки:

```json
{"detail":"Логин уже занят"}
```

Например, запрос папок без токена возвращает `401`:

```bash
curl -i http://localhost:8000/api/v1/folders
```

## Тесты и спецификация

Тесты используют отдельную MongoDB-базу `maildb_test`.
Перед тестами запустите MongoDB и примените к этой базе валидаторы:

```bash
docker compose up -d mongo
docker compose exec -T mongo mongosh --quiet maildb_test --file /docker-entrypoint-initdb.d/01-validation.js
```

После активации виртуального окружения:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Перед каждым тестом и после него документы тестовой базы очищаются.
Переменная `TEST_MONGO_DB` позволяет выбрать другое имя, оканчивающееся на `_test`.
Для другого сервера задайте `MONGO_URI` перед запуском Python. Валидаторы должны
быть применены к тестовой базе этого сервера. Рабочая `maildb` тестами не очищается.

Тесты проверяют все операции API, поиск по маскам, уникальность логина и папки,
невалидные данные, отсутствующие ресурсы, неверные и истёкшие токены,
недоступность чужих папок и писем, валидацию MongoDB и сохранение данных после
потери сессии. При попытке вставить невалидные документы проверяется ошибка `121`.
Также проверяются Swagger и соответствие файла OpenAPI серверу.

`openapi.yaml` содержит параметры, модели запросов/ответов, примеры и схему
Bearer-аутентификации. Пересоздать спецификацию после изменения API:

```bash
python generate_openapi.py
```

## Ограничения учебного решения

Пользователи, папки и письма сохраняются в MongoDB и переживают перезапуск API.
Сессионные токены остались в памяти: после перезапуска API нужен повторный вход.
Нужен один процесс Uvicorn, поскольку несколько workers не разделяют сессии.
Письмо сохраняется в папке; доставка через SMTP и интеграция с Outlook в задание не входят.

## Файлы проекта

```text
main.py                  # endpoints, middleware и запросы PyMongo
database.py              # подключение MongoClient
models.py                # прежние DTO запросов и ответов
mongodb/
  schema_design.md       # документная модель и обоснование связей
  validation.js          # коллекции, JSON Schema и индексы
  data.js                # по 10 документов в коллекции
  queries.js             # операции варианта, Update/Delete и операторы
postgresql/              # материалы домашней работы 03
  schema.sql             # таблицы, ограничения и индексы
  data.sql               # по 10 записей в таблице
  queries.sql            # восемь операций варианта
  optimization.md        # сравнение планов EXPLAIN
requirements.txt
requirements-dev.txt
generate_openapi.py
openapi.yaml
tests/test_api.py
Dockerfile
docker-compose.yaml
README.md
```
