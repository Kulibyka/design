# Домашнее задание 06. События и CQRS для электронной почты

Вариант 9. Приложение содержит пользователей, почтовые папки и сообщения.
Реализованы все восемь операций варианта и вход пользователя.

Используются Python 3.12, FastAPI, Pydantic, MongoDB 7, RabbitMQ 4 и драйверы PyMongo/Pika.
Все три сущности теперь хранятся в MongoDB. Пути API и форматы запросов и ответов
из домашней работы 02 сохранены.

Добавлены кеширование двух списков в памяти Python и ограничение попыток входа.
Механизм работы, выбор стратегий, требования и метрики описаны в
[performance_design.md](performance_design.md).

Команды создания публикуют события в RabbitMQ. Отдельный consumer сохраняет
проекции для чтения в MongoDB. Архитектура и механизм описаны в
[event_driven_design.md](event_driven_design.md), события — в
[event_catalog.md](event_catalog.md).

## Запуск API и MongoDB через Docker

Из папки проекта, где находится `docker-compose.yml`:

```bash
docker compose up --build
```

Запускаются `api`, `mongo`, `rabbitmq` и `consumer`. API слушает порт 8000,
MongoDB — 27017, RabbitMQ — 5672. API и consumer ждут готовности MongoDB и RabbitMQ.
При первом запуске в пустом MongoDB volume
автоматически выполняются `mongodb/validation.js` и `mongodb/data.js`: создаются база `maildb`,
коллекции, валидаторы, индексы и по 10 документов в `users`, `folders`, `messages`.

Можно войти под логином `user01` с паролем `example-password`.
У пользователя уже есть папка «Inbox» и одно письмо.

Swagger UI доступен по пути `/docs`, спецификация — `/openapi.json`.
В Swagger можно зарегистрироваться, выполнить вход и вставить `access_token`
в окно **Authorize**.

Остановка сохраняет данные MongoDB и очередь RabbitMQ в volumes:

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

MongoDB, RabbitMQ и consumer остаются в Docker:

```bash
docker compose up -d --build mongo rabbitmq consumer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB="maildb"
export AMQP_URL="amqp://mail:mail_password@localhost:5672/%2F"
uvicorn main:app --reload
```

В cmd.exe активация и переменные задаются так:

```cmd
.venv\Scripts\activate
set "MONGO_URI=mongodb://localhost:27017"
set "MONGO_DB=maildb"
set "AMQP_URL=amqp://mail:mail_password@localhost:5672/%2F"
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
| `mail_read_model` | `_id`, `entity_type`, публичный DTO в `data`, `event_id`, `occurred_at`, `applied_at` |

UUID хранятся как String, даты — Date, содержимое письма — вложенный Object,
адрес получателя — Array из одной строки, размер текста в UTF-8 — Number.
`user_id` ссылается на пользователя, `folder_id` — на папку.
Обоснование embedded/references и примеры документов находятся в `mongodb/schema_design.md`.

В `mongodb/validation.js` заданы `$jsonSchema`, обязательные поля, BSON-типы,
ограничения строк, массива и числа. Скрипт создаёт уникальные индексы логина
и имени папки у владельца, а также индекс чтения писем папки.
Проекции `mail_read_model` создаёт consumer по событиям новых объектов.

## События и CQRS

Три POST-команды после записи в MongoDB публикуют `UserCreated`, `FolderCreated`
и `MessageCreated`. Producer отправляет persistent JSON в topic exchange
`mail.events`; очередь `mail.read_model` подписана на `*.created`.
Consumer строит проекции и подтверждает сообщение только после записи в БД.
Повторная доставка не создаёт дубль благодаря upsert по UUID сущности.

`GET /api/v1/messages/{code}` читает готовую проекцию. Пока её нет, он использует
исходное письмо. Поэтому старые данные и только что созданные письма доступны
сразу. Владелец папки проверяется в обоих случаях. Остальные GET сохраняют
прежние запросы и кеширование. Это частичное применение CQRS с асинхронной
синхронизацией модели чтения событиями.

### Проверить взаимодействие

Запустите проект, выполните регистрацию, вход, создание папки и письма по
HTTP-примерам ниже. Посмотреть обработанные события:

```bash
docker compose logs -f consumer
```

В логах появятся `Processed UserCreated`, `Processed FolderCreated` и
`Processed MessageCreated`. Проекции можно посмотреть в mongosh:

```bash
docker compose exec mongo mongosh maildb
```

```javascript
db.mail_read_model.find()
db.mail_read_model.find({entity_type: "message"})
db.mail_read_model.findOne({_id: "message:PASTE_MESSAGE_CODE_HERE"})
```

Чтобы проверить накопление событий, остановите consumer, создайте письмо через
API и запустите consumer снова:

```bash
docker compose stop consumer
docker compose start consumer
```

Между двумя командами выполните POST создания письма. Пока consumer остановлен,
событие ждёт в очереди, GET письма работает через исходную коллекцию. После
старта consumer появится проекция.

Веб-интерфейс RabbitMQ: `http://localhost:15672`, учебный логин `mail`, пароль
`mail_password`. В разделе Queues можно проверить очередь `mail.read_model`,
число Ready/Unacked и наличие consumer. Состояние через командную строку:

```bash
docker compose exec rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

### Если публикация не подтверждена

При недоступном RabbitMQ команда возвращает `503`, хотя объект уже сохранён
в MongoDB. Подтверждение брокера могло потеряться, поэтому событие также могло
быть принято. Проверяйте сохранённые данные перед повторным созданием.
После восстановления брокера можно опубликовать событие для сохранённого письма:

```bash
docker compose exec -T api python - <<'PY'
from database import get_database
from events.producer import publish_event
from main import message_response

message = get_database().messages.find_one({"_id": "PASTE_MESSAGE_CODE_HERE"})
if message is None:
    raise ValueError("Message not found")
event = publish_event("MessageCreated", message_response(message).model_dump(mode="json"))
print(event["event_id"])
PY
```

Новый event_id не создаст второй документ проекции того же письма.
Граница гарантии at-least-once и причины повторной доставки разобраны в
`event_driven_design.md`.

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

## Кеширование и ограничение запросов

Используется Cache-Aside: сначала проверяется словарь Python, при промахе
данные читаются из MongoDB и сохраняются на ограниченное время.

| Чтение | TTL | Инвалидация |
| --- | --- | --- |
| `GET /api/v1/folders` | 30 секунд | После создания папки пользователя |
| `GET /api/v1/folders/{folder_id}/messages` | 15 секунд | После создания письма в папке |

Ключи содержат владельца; для писем также UUID папки. Токен проверяется до
обращения к кешу, владелец папки писем — при каждом чтении. Кешируются только
успешные списки, включая пустые. Заголовок `X-Cache: MISS` означает загрузку
из MongoDB, `X-Cache: HIT` — повторное использование списка. При HIT списка писем
проверка папки в БД всё равно выполняется.

`POST /api/v1/auth/login` ограничен алгоритмом Fixed Window Counter:
10 попыток в минуту с одного IP. Успешные и ошибочные попытки расходуют лимит.
После исчерпания API возвращает `429` до обращения к БД и проверки пароля.
На границе следующей минуты счётчик обновляется.

Ответы входа содержат `X-RateLimit-Limit`, `X-RateLimit-Remaining` и
`X-RateLimit-Reset`. Последний — Unix timestamp начала следующего окна в секундах.
Redis и дополнительные зависимости не используются. Кеш и лимиты действуют
в одном процессе и очищаются при его перезапуске.

### Проверить кеш

После входа дважды выполнить запрос своей папки или списка папок:

```bash
curl -i http://localhost:8000/api/v1/folders -H "Authorization: Bearer $TOKEN"
curl -i http://localhost:8000/api/v1/folders -H "Authorization: Bearer $TOKEN"
```

Если кеш был пуст, первый ответ содержит MISS, второй — HIT. После создания
новой папки следующее чтение должно вернуть MISS и актуальный список.
Аналогично работают чтение и создание писем. Изменения напрямую через `mongosh`
обновят списки после TTL.

### Проверить лимит входа

В Bash выполнить 11 запросов подряд в пределах одного минутного окна:

```bash
for i in {1..11}; do
  curl -i -X POST http://localhost:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"login":"missing-user","password":"wrong-password"}'
done
```

Если в этом окне ещё не было попыток, первые десять ответов будут `401`,
одиннадцатый — `429` с `X-RateLimit-Remaining: 0`. Попытки входа, выполненные
ранее с того же IP, тоже учитываются. Для повторения дождитесь времени из
`X-RateLimit-Reset`. При переходе через границу минуты серия может не получить `429`.

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

## Проверка через Postman

Коллекция: [postman/Mail_API.postman_collection.json](postman/Mail_API.postman_collection.json).
В ней 35 запросов с автоматическими проверками ответов:

1. Основной сценарий: восемь операций варианта и вход.
2. Кеш, повторное чтение и инвалидация после создания.
3. Ошибки `400`, `401`, `404`, `409`.
4. Отказ в доступе к папке и письму другого пользователя.
5. Лимит входа и заголовки `X-RateLimit-*`.

Запустите приложение, в Postman нажмите **Import** и выберите JSON-файл.
Выберите **No Environment**: все необходимые переменные уже находятся в коллекции.
`base_url` по умолчанию равен `http://localhost:8000`; для другого адреса измените
эту переменную. Отдельный environment-файл не нужен.

Выполняйте запросы папок 01–04 по порядку или запустите их через **Runner**
с одной итерацией и без задержки. Регистрация каждый раз создаёт уникальный логин;
токен, UUID папки и код письма сохраняются автоматически. Результаты проверок
видны в **Test Results**. Для проверки HIT выполняйте папку кеша подряд:
пауза больше TTL приводит к новому MISS.

Для проверки `429` выберите в Runner только папку 05, задайте **Iterations = 11**
и **Delay = 0**. Предыдущие попытки входа с того же IP учитываются, поэтому
блокировка может наступить раньше. Серия должна укладываться в одно минутное
окно; если она пересекла границу, повторите её в начале следующего окна.
При `429` на обычном входе дождитесь времени `X-RateLimit-Reset`.

Основная папка подходит заданиям 02–06; проверки кеша и лимитов — версиям 05–06.
Тела запросов используют латиницу. Создание объектов в версии 06 публикует события;
обработку RabbitMQ проверяйте через `docker compose logs -f consumer`.
Коллекция создаёт демонстрационные записи; HTTP-операций удаления в проекте нет.
Коллекция проверена через Newman на отдельной базе: все 35 запросов и 73 проверки
ответов прошли. Отдельный запуск папки лимита на 11 итераций прошёл 43 проверки
и подтвердил ответы `429`. Consumer обработал шесть событий создания.

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
| `429 Too Many Requests` | Исчерпаны попытки входа с данного IP в текущей минуте |
| `503 Service Unavailable` | Объект уже сохранён, но публикация события в RabbitMQ не подтверждена |

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
Перед тестами запустите MongoDB и RabbitMQ, затем примените валидаторы:

```bash
docker compose up -d --wait mongo rabbitmq
docker compose exec -T mongo mongosh --quiet maildb_test --file /docker-entrypoint-initdb.d/01-validation.js
```

После активации виртуального окружения:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Перед каждым тестом и после него документы тестовой базы очищаются, включая проекции.
Переменная `TEST_MONGO_DB` позволяет выбрать другое имя, оканчивающееся на `_test`.
Для другого сервера задайте `MONGO_URI` перед запуском Python. Валидаторы должны
быть применены к тестовой базе этого сервера. Рабочая `maildb` тестами не очищается.
API-тесты подменяют публикацию, чтобы не отправлять события в рабочую очередь.
Тесты producer/consumer используют настоящий RabbitMQ, отдельные временные
exchange/queue и базу `mail_events_test` (переменная `TEST_EVENT_DB`, суффикс `_test`).
Временные exchange/queue удаляются после проверок. Для другого брокера задайте
`AMQP_URL` перед запуском Python.

Тесты проверяют все операции API, поиск по маскам, уникальность логина и папки,
невалидные данные, отсутствующие ресурсы, неверные и истёкшие токены,
недоступность чужих папок и писем, валидацию MongoDB и сохранение данных после
потери сессии. При попытке вставить невалидные документы проверяется ошибка `121`.
Также проверяются Swagger и соответствие файла OpenAPI серверу.
Проверки кеша подтверждают уменьшение выборок MongoDB, TTL, инвалидацию и
сохранение проверки доступа. Проверки rate limiting охватывают заголовки,
блокировку, сброс окна, разные IP и параллельные запросы.
Для событий проверяются три routing key, формат и persistent-сообщения,
создание проекций, ack, повторная доставка, отсутствие дублей, ошибка MongoDB,
невалидное событие и чтение проекции с контролем доступа.

`openapi.yaml` содержит параметры, модели запросов/ответов, примеры и схему
Bearer-аутентификации. Пересоздать спецификацию после изменения API:

```bash
python generate_openapi.py
```

## Ограничения учебного решения

Пользователи, папки и письма сохраняются в MongoDB и переживают перезапуск API.
Проекции и принятые RabbitMQ-сообщения также сохраняются в volumes. Между записью
объекта и публикацией события нет общей транзакции. Read model обновляется
асинхронно; прямые изменения через mongosh не обновляют существующую проекцию.
Сессии, кеш и лимиты находятся в памяти: после перезапуска API нужен повторный вход.
Нужен один процесс Uvicorn, поскольку несколько workers не разделяют это состояние.
Письмо сохраняется в папке; доставка через SMTP и интеграция с Outlook в задание не входят.

## Файлы проекта

```text
main.py                  # endpoints, middleware и запросы PyMongo
database.py              # подключение MongoClient
models.py                # прежние DTO запросов и ответов
performance.py           # TTL-кеш и Fixed Window Counter в памяти
performance_design.md    # механизм, стратегии, требования и метрики
events/
  schema.py              # конверт события версии 1
  broker.py              # подключение, exchange, queue и routing
  producer.py            # публикация с подтверждением RabbitMQ
  consumer.py            # обработка и идемпотентная модель чтения
event_driven_design.md   # архитектура, CQRS, гарантии и ограничения
event_catalog.md         # три события и их payload
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
tests/test_events.py
postman/Mail_API.postman_collection.json
Dockerfile
docker-compose.yml
README.md
```
