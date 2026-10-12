// Восемь операций варианта и обязательные примеры Update/Delete.
// Скрипт меняет и удаляет только созданные им демонстрационные документы.
const demoUserId = "11111111-1111-4111-8111-111111111111";
const demoFolderId = "22222222-2222-4222-8222-222222222222";
const demoMessageCode = "33333333-3333-4333-8333-333333333333";

function check(condition, message = "Query check failed") {
    if (!condition) throw new Error(message);
}
check(db.users.findOne({_id: demoUserId}) === null, "Demo user ID is already occupied");
check(db.folders.findOne({_id: demoFolderId}) === null, "Demo folder ID is already occupied");
check(db.messages.findOne({_id: demoMessageCode}) === null, "Demo message ID is already occupied");

try {
    // 1. Создание пользователя. API заранее хеширует пароль и приводит логин к нижнему регистру.
    db.users.insertOne({
        _id: demoUserId, login: "demo_user", first_name: "Ivan", last_name: "Petrov",
        password_hash: "$argon2id$v=19$m=65536,t=3,p=4$cjrweZivnffTJhze9PgvSg$luEiJ2OeKObGJmBAkKnjePH4CycsfgI4pcweBQTL6Ls",
        created_at: new Date()
    });

    // 2. Поиск пользователя по логину, без выдачи хеша пароля.
    printjson(db.users.findOne({login: {$eq: "demo_user"}}, {password_hash: 0}));

    // 3. Маски Iv* и Pet?ov. API экранирует исходный текст перед заменой * и ?.
    db.users.find({$and: [
        {first_name: {$regex: "^Iv.*$", $options: "i"}},
        {last_name: {$regex: "^Pet.ov$", $options: "i"}}
    ]}, {password_hash: 0}).sort({login: 1}).forEach(document => printjson(document));

    // 4. Создание папки пользователя.
    db.folders.insertOne({
        _id: demoFolderId, user_id: demoUserId, name: "Demo folder", created_at: new Date()
    });

    // 5. Перечень папок текущего пользователя.
    db.folders.find({user_id: {$eq: demoUserId}}).sort({name: 1, _id: 1})
        .forEach(document => printjson(document));

    // 6. Создание письма после проверки владельца папки.
    check(db.folders.findOne({_id: demoFolderId, user_id: demoUserId}) !== null);
    const demoBody = "Project description.";
    db.messages.insertOne({
        _id: demoMessageCode, folder_id: demoFolderId,
        content: {subject: "Homework", body: demoBody},
        recipients: ["teacher@example.com"], size_bytes: NumberInt(demoBody.length),
        created_at: new Date()
    });

    // 7. Все письма папки: сначала проверка владельца, затем чтение коллекции писем.
    check(db.folders.findOne({_id: demoFolderId, user_id: demoUserId}) !== null);
    db.messages.find({folder_id: demoFolderId}).sort({created_at: 1, _id: 1})
        .forEach(document => printjson(document));

    // 8. Письмо по коду с проверкой владельца.
    const foundMessage = db.messages.findOne({_id: demoMessageCode});
    check(foundMessage !== null);
    check(db.folders.findOne({_id: foundMessage.folder_id, user_id: demoUserId}) !== null);
    printjson(foundMessage);

    // Условия с операторами $eq, $ne, $gt, $lt, $in, $and, $or.
    const selected = db.messages.find({$and: [
        {folder_id: {$eq: demoFolderId}},
        {"content.body": {$ne: ""}},
        {size_bytes: {$gt: 0, $lt: 1024}},
        {recipients: {$in: ["teacher@example.com"]}},
        {$or: [{"content.subject": {$eq: "Homework"}}, {"content.subject": {$eq: "Exam"}}]}
    ]}).toArray();
    check(selected.length === 1);
    printjson(selected);

    // Update: обновление по одному документу каждой коллекции.
    check(db.users.updateOne({_id: demoUserId}, {$set: {first_name: "Alexey"}}).modifiedCount === 1);
    check(db.folders.updateOne({_id: demoFolderId, user_id: demoUserId},
        {$set: {name: "Updated demo folder"}}).modifiedCount === 1);
    const updatedBody = "Updated project description.";
    check(db.messages.updateOne({_id: demoMessageCode, folder_id: demoFolderId}, {$set: {
        "content.subject": "Updated homework", "content.body": updatedBody,
        size_bytes: NumberInt(updatedBody.length)
    }}).modifiedCount === 1);

    // Delete: сначала письмо, затем папка и пользователь, чтобы не оставить ссылки.
    check(db.messages.deleteOne({_id: demoMessageCode}).deletedCount === 1);
    check(db.folders.deleteOne({_id: demoFolderId, user_id: demoUserId}).deletedCount === 1);
    check(db.users.deleteOne({_id: demoUserId}).deletedCount === 1);
    print("All variant operations, filters, updates and deletes passed");
} finally {
    // Очистка также выполняется при ошибке в одном из примеров.
    db.messages.deleteOne({_id: demoMessageCode});
    db.folders.deleteOne({_id: demoFolderId});
    db.users.deleteOne({_id: demoUserId});
}
