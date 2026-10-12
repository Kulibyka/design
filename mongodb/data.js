// По 10 документов в каждой коллекции. Пароль пользователей: example-password.
const seedPasswordHash = "$argon2id$v=19$m=65536,t=3,p=4$cjrweZivnffTJhze9PgvSg$luEiJ2OeKObGJmBAkKnjePH4CycsfgI4pcweBQTL6Ls";
const seedNames = [
    ["Ivan", "Petrov"], ["Anna", "Ivanova"], ["Petr", "Sidorov"],
    ["Maria", "Smirnova"], ["Alexey", "Kuznetsov"], ["Elena", "Popova"],
    ["Dmitry", "Vasilyev"], ["Olga", "Sokolova"], ["Sergey", "Mikhailov"],
    ["Natalia", "Fedorova"]
];

for (let n = 1; n <= 10; n++) {
    const suffix = String(n).padStart(12, "0");
    const userId = "10000000-0000-4000-8000-" + suffix;
    const folderId = "20000000-0000-4000-8000-" + suffix;
    const messageCode = "30000000-0000-4000-8000-" + suffix;
    const createdAt = new Date("2026-10-12T12:00:00Z");
    const body = "Example message for homework 04.";

    db.users.updateOne({_id: userId}, {$setOnInsert: {
        _id: userId,
        login: "user" + String(n).padStart(2, "0"),
        first_name: seedNames[n - 1][0],
        last_name: seedNames[n - 1][1],
        password_hash: seedPasswordHash,
        created_at: createdAt
    }}, {upsert: true});

    db.folders.updateOne({_id: folderId}, {$setOnInsert: {
        _id: folderId, user_id: userId, name: "Inbox", created_at: createdAt
    }}, {upsert: true});

    db.messages.updateOne({_id: messageCode}, {$setOnInsert: {
        _id: messageCode,
        folder_id: folderId,
        content: {subject: "Test message " + n, body: body},
        recipients: ["teacher@example.com"],
        size_bytes: NumberInt(body.length), // Текст примера ASCII: символы равны байтам UTF-8.
        created_at: createdAt
    }}, {upsert: true});
}
print("Seed data ready: " + db.users.countDocuments({}) + " users, "
    + db.folders.countDocuments({}) + " folders, " + db.messages.countDocuments({}) + " messages");
