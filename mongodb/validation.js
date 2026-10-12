// Скрипт выполняется в выбранной базе: mongosh maildb --file mongodb/validation.js.
const uuidString = {
    bsonType: "string",
    pattern: "^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$"
};
const nonEmptyString = {bsonType: "string", minLength: 1, pattern: "\\S"};
const emailString = {
    bsonType: "string",
    pattern: "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$"
};

const schemas = {
    users: {
        bsonType: "object",
        required: ["_id", "login", "first_name", "last_name", "password_hash", "created_at"],
        additionalProperties: false,
        properties: {
            _id: uuidString,
            login: nonEmptyString,
            first_name: nonEmptyString,
            last_name: nonEmptyString,
            password_hash: {bsonType: "string", pattern: "^\\$argon2id\\$"},
            created_at: {bsonType: "date"}
        }
    },
    folders: {
        bsonType: "object",
        required: ["_id", "user_id", "name", "created_at"],
        additionalProperties: false,
        properties: {
            _id: uuidString,
            user_id: uuidString,
            name: nonEmptyString,
            created_at: {bsonType: "date"}
        }
    },
    messages: {
        bsonType: "object",
        required: ["_id", "folder_id", "content", "recipients", "size_bytes", "created_at"],
        additionalProperties: false,
        properties: {
            _id: uuidString,
            folder_id: uuidString,
            content: {
                bsonType: "object",
                required: ["subject", "body"],
                additionalProperties: false,
                properties: {subject: nonEmptyString, body: nonEmptyString}
            },
            recipients: {
                bsonType: "array",
                minItems: 1,
                maxItems: 1,
                items: emailString
            },
            size_bytes: {bsonType: ["int", "long"], minimum: 1},
            created_at: {bsonType: "date"}
        }
    }
};

for (const [name, schema] of Object.entries(schemas)) {
    const options = {
        validator: {$jsonSchema: schema},
        validationLevel: "strict",
        validationAction: "error"
    };
    if (db.getCollectionNames().includes(name)) {
        db.runCommand({collMod: name, ...options});
    } else {
        db.createCollection(name, options);
    }
}

db.users.createIndex({login: 1}, {unique: true, name: "users_login_unique"});
db.folders.createIndex({user_id: 1, name: 1}, {unique: true, name: "folders_owner_name_unique"});
db.messages.createIndex({folder_id: 1, created_at: 1, _id: 1}, {name: "messages_folder_created"});
print("Collections, validators and indexes are ready in " + db.getName());
