# Каталог событий — домашнее задание 06

Версия схемы: 1. События публикуются после записи сущности в MongoDB.
Все UUID в JSON — строки, даты — ISO 8601 UTC. События не содержат паролей,
хешей и сессионных токенов.

## Общий конверт

Все пять полей обязательны:

| Поле | Тип | Назначение |
| --- | --- | --- |
| `event_id` | String, UUID | Идентификатор публикации |
| `event_type` | String | UserCreated, FolderCreated или MessageCreated |
| `version` | Number, 1 | Версия формата |
| `occurred_at` | String, ISO 8601 UTC | Время формирования события producer |
| `payload` | Object | Публичные данные созданного объекта |

```json
{
  "event_id": "44444444-4444-4444-8444-444444444444",
  "event_type": "UserCreated",
  "version": 1,
  "occurred_at": "2026-10-12T12:00:00Z",
  "payload": {
    "id": "11111111-1111-4111-8111-111111111111",
    "login": "ivan",
    "first_name": "Ivan",
    "last_name": "Petrov",
    "created_at": "2026-10-12T12:00:00Z"
  }
}
```

Транспорт: JSON UTF-8, exchange `mail.events` типа topic, queue `mail.read_model`,
binding `*.created`. Свойства сообщения: `content_type=application/json`,
`content_encoding=utf-8`, `delivery_mode=2`, `message_id=event_id`, `type=event_type`.

## UserCreated

- Команда: CreateUser, `POST /api/v1/users`.
- Производитель: FastAPI, функция `create_user` через `events.producer.publish_event`.
- Routing key: `user.created`.
- Потребитель: consumer модели чтения, `events.consumer`.
- Результат: проекция `user:<id>` в `mail_read_model`.
- Доставка: at-least-once после подтверждения брокером; повторная обработка идемпотентна.

| Поле payload | Тип | Описание |
| --- | --- | --- |
| `id` | String, UUID | Идентификатор пользователя |
| `login` | String | Нормализованный логин в нижнем регистре |
| `first_name` | String | Имя |
| `last_name` | String | Фамилия |
| `created_at` | String, ISO 8601 UTC | Время создания пользователя |

Пример payload приведён в общем конверте выше. Хеш используется только
в исходной коллекции `users` и в событие не передаётся.

## FolderCreated

- Команда: CreateFolder, `POST /api/v1/folders`.
- Производитель: FastAPI, функция `create_folder` через `events.producer.publish_event`.
- Routing key: `folder.created`.
- Потребитель: consumer модели чтения, `events.consumer`.
- Результат: проекция `folder:<id>` в `mail_read_model`.
- Доставка: at-least-once после подтверждения брокером; повторная обработка идемпотентна.

| Поле payload | Тип | Описание |
| --- | --- | --- |
| `id` | String, UUID | Идентификатор папки |
| `user_id` | String, UUID | Владелец из сессии API |
| `name` | String | Название папки |
| `created_at` | String, ISO 8601 UTC | Время создания папки |

```json
{
  "id": "22222222-2222-4222-8222-222222222222",
  "user_id": "11111111-1111-4111-8111-111111111111",
  "name": "Study",
  "created_at": "2026-10-12T12:00:00Z"
}
```

## MessageCreated

- Команда: CreateMessage, `POST /api/v1/folders/{folder_id}/messages`.
- Производитель: FastAPI, функция `create_message` через `events.producer.publish_event`.
- Routing key: `message.created`.
- Потребитель: consumer модели чтения, `events.consumer`.
- Результат: проекция `message:<code>` в `mail_read_model`, используемая GET письма по коду.
- Доставка: at-least-once после подтверждения брокером; повторная обработка идемпотентна.

| Поле payload | Тип | Описание |
| --- | --- | --- |
| `code` | String, UUID | Код письма |
| `folder_id` | String, UUID | Папка письма |
| `subject` | String | Тема |
| `body` | String | Текст |
| `recipient_address` | String, email | Адрес получателя |
| `created_at` | String, ISO 8601 UTC | Время создания письма |

```json
{
  "code": "33333333-3333-4333-8333-333333333333",
  "folder_id": "22222222-2222-4222-8222-222222222222",
  "subject": "Homework",
  "body": "Project description.",
  "recipient_address": "teacher@example.com",
  "created_at": "2026-10-12T12:00:00Z"
}
```

## Общие условия обработки

Consumer проверяет конверт через `Event`, payload — через соответствующий
публичный DTO. Подтверждение ack выполняется после записи проекции.
Ключ `тип сущности:UUID` и `$setOnInsert` обеспечивают одинаковый результат
повторной обработки событий создания. Ошибка MongoDB возвращает событие
в очередь; невалидное событие удаляется с предупреждением в логе.

Гарантия доставки относится к принятым брокером корректным событиям.
Между записью объекта в БД и публикацией есть возможность сбоя; тогда API
возвращает `503`, хотя объект уже сохранён. Это не exactly-once и не атомарная
запись в две системы. Подробности и CQRS описаны в
[event_driven_design.md](event_driven_design.md).
