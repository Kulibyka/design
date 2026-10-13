workspace "Электронная почта — вариант 9" "План архитектуры сервиса электронной почты" {
    model {
        user = person "Пользователь" "Будет регистрироваться, входить и работать со своей почтой."

        mail = softwareSystem "Электронная почта" "Позволит искать пользователей, создавать папки и хранить письма." {
            api = container "REST API" "Регистрация и вход; пользователи, папки и письма. Кеш и сессии будут храниться в памяти процесса." "Python 3.12, FastAPI" {
                tags "API"
            }
            database = container "Хранилище почты" "Коллекции users, folders, messages и mail_read_model. Основные данные и проекции будут храниться в одной базе." "MongoDB 7" {
                tags "Database"
            }
            broker = container "Брокер событий" "Будет принимать события создания и хранить их до обработки. Exchange mail.events; очередь mail.read_model." "RabbitMQ 4" {
                tags "Broker"
            }
            consumer = container "Обработчик событий" "Будет получать события и сохранять проекции для чтения. Повторная обработка не создаст дубликат." "Python 3.12, Pika, PyMongo" {
                tags "Worker"
            }
        }

        user -> mail "Будет работать с пользователями, папками и письмами" "HTTP/REST, JSON"
        user -> api "Регистрация, вход и работа с почтой" "HTTP/REST, JSON"
        api -> database "Чтение и запись; проверка владельца" "MongoDB Wire Protocol/TCP"
        api -> broker "События создания объектов" "AMQP 0-9-1, Pika"
        broker -> consumer "Доставка событий из очереди mail.read_model" "AMQP 0-9-1, Pika"
        consumer -> database "Запись проекций в mail_read_model" "MongoDB Wire Protocol/TCP"
    }

    views {
        systemContext mail "SystemContext" {
            title "C1 · Контекст сервиса электронной почты"
            include user mail
            autoLayout lr
        }

        container mail "Containers" {
            title "C2 · Контейнеры и их взаимодействие"
            include *
            autoLayout lr
        }

        dynamic mail "CreateMessage" {
            title "Dynamic · Создание письма в своей папке"
            properties {
                "plantuml.sequenceDiagram" "true"
            }
            user -> api "POST /api/v1/folders/{folder_id}/messages"
            api -> database "Проверить папку и её владельца"
            api -> database "Сохранить письмо в messages"
            api -> broker "Опубликовать MessageCreated"
            broker -> api "Подтвердить приём события"
            api -> user "201 Created: вернуть код письма"
            broker -> consumer "Доставить событие из очереди"
            consumer -> database "Сохранить проекцию письма в mail_read_model"
            consumer -> broker "ACK после записи проекции"
            autoLayout lr
        }

        styles {
            element "Element" {
                fontSize 22
                color #18334A
                stroke #CBD5E1
            }
            element "Person" {
                shape Person
                background #475569
                color #FFFFFF
                width 300
                height 190
            }
            element "Software System" {
                shape RoundedBox
                background #0F766E
                color #FFFFFF
                stroke #64748B
                width 460
                height 240
            }
            element "Container" {
                shape RoundedBox
                background #EFF6FF
                width 410
                height 240
            }
            element "API" {
                background #164E63
                color #FFFFFF
            }
            element "Database" {
                shape Cylinder
                background #EDE9FE
                color #3B2B64
            }
            element "Broker" {
                background #FEF3C7
                color #714A12
            }
            element "Worker" {
                background #DBEAFE
                color #1E3A5F
            }
            relationship "Relationship" {
                color #475569
                fontSize 20
                thickness 2
            }
        }
    }
}
