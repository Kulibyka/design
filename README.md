# Домашнее задание 02. REST API сервиса электронной почты

Вариант 9. Приложение содержит пользователей, почтовые папки и сообщения.
Реализованы все восемь операций варианта и вход пользователя.

Используются Python 3.12, FastAPI и Pydantic. Данные хранятся в словарях в памяти,
как разрешено в задании. Это один учебный сервис. Имена ресурсов и поля взяты
из описания проекта в домашней работе 01.

## Запуск

Из корня проекта:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

В Windows вместо `source .venv/bin/activate` используется `.venv\Scripts\activate`.

API слушает порт 8000. Swagger UI доступен по пути `/docs`,
JSON-спецификация — `/openapi.json`. В Swagger можно зарегистрироваться,
выполнить вход и вставить значение `access_token` в окно **Authorize**.

## Запуск через Docker

```bash
docker compose up --build
```

Порт API — 8000. Остановить контейнер:

```bash
docker compose down
```

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
  -d '{"login":"ivan","first_name":"Иван","last_name":"Петров","password":"example-password"}'
```

Ответ `201 Created`:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "login": "ivan",
  "first_name": "Иван",
  "last_name": "Петров",
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
TOKEN='вставьте access_token из ответа'
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
  --data-urlencode 'first_name_mask=Ив*' --data-urlencode 'last_name_mask=Пет?ов'
```

Ответ `200 OK` — массив объектов пользователя:

```json
[{"id":"11111111-1111-4111-8111-111111111111","login":"ivan","first_name":"Иван","last_name":"Петров","created_at":"2026-10-12T12:00:00Z"}]
```

### Создание папки

```bash
curl -i -X POST http://localhost:8000/api/v1/folders \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Учёба"}'
```

Ответ `201 Created`:

```json
{"id":"22222222-2222-4222-8222-222222222222","user_id":"11111111-1111-4111-8111-111111111111","name":"Учёба","created_at":"2026-10-12T12:00:00Z"}
```

### Список папок

```bash
curl http://localhost:8000/api/v1/folders -H "Authorization: Bearer $TOKEN"
```

Ответ `200 OK` — массив папок:

```json
[{"id":"22222222-2222-4222-8222-222222222222","user_id":"11111111-1111-4111-8111-111111111111","name":"Учёба","created_at":"2026-10-12T12:00:00Z"}]
```

### Создание письма в папке

```bash
FOLDER_ID='вставьте id созданной папки'
curl -i -X POST "http://localhost:8000/api/v1/folders/$FOLDER_ID/messages" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"subject":"Домашнее задание","body":"Отправляю описание архитектуры.","recipient_address":"teacher@example.com"}'
```

Ответ `201 Created`:

```json
{"code":"33333333-3333-4333-8333-333333333333","folder_id":"22222222-2222-4222-8222-222222222222","subject":"Домашнее задание","body":"Отправляю описание архитектуры.","recipient_address":"teacher@example.com","created_at":"2026-10-12T12:00:00Z"}
```

### Список писем папки

```bash
curl "http://localhost:8000/api/v1/folders/$FOLDER_ID/messages" -H "Authorization: Bearer $TOKEN"
```

Ответ `200 OK` — массив писем, например:

```json
[{"code":"33333333-3333-4333-8333-333333333333","folder_id":"22222222-2222-4222-8222-222222222222","subject":"Домашнее задание","body":"Отправляю описание архитектуры.","recipient_address":"teacher@example.com","created_at":"2026-10-12T12:00:00Z"}]
```

### Получение письма по коду

```bash
CODE='вставьте code созданного письма'
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

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Тесты проверяют все операции, поиск по маскам, уникальность логина и папки,
невалидные данные, отсутствующие ресурсы, неверные и истёкшие токены,
недоступность чужих папок и писем, Swagger и соответствие файла OpenAPI серверу.

`openapi.yaml` содержит параметры, модели запросов/ответов, примеры и схему
Bearer-аутентификации. Пересоздать спецификацию после изменения API:

```bash
python generate_openapi.py
```

## Ограничения учебного решения

Данные и токены теряются при перезапуске сервера. Нужен один процесс Uvicorn:
несколько workers не разделяют словари. Письмо сохраняется в папке;
доставка через SMTP и интеграция с Outlook в задание не входят.

## Файлы проекта

```text
main.py                  # endpoints, middleware и хранилище
models.py                # DTO запросов и ответов
requirements.txt         # зависимости сервиса
requirements-dev.txt     # зависимости тестов и генератора спецификации
generate_openapi.py      # сохранение спецификации
openapi.yaml             # OpenAPI
tests/test_api.py        # тесты
Dockerfile
docker-compose.yaml
README.md
```
