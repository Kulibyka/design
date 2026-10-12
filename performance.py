"""Кеш с TTL и счётчик запросов в памяти одного процесса."""

from threading import Lock
from time import monotonic, time


class TTLCache:
    def __init__(self, ttl_seconds: int, max_entries: int = 1000):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.entries = {}
        self.lock = Lock()

    def get_or_load(self, key, load):
        # Загрузка и сброс используют один lock: устаревший результат не сможет
        # записаться в кеш после инвалидации, выполненной операцией создания.
        with self.lock:
            now = monotonic()
            expired = [key for key, (_, expires_at) in self.entries.items() if expires_at <= now]
            for expired_key in expired:
                del self.entries[expired_key]
            if key in self.entries:
                return self.entries[key][0], "HIT"
            value = load()
            if len(self.entries) >= self.max_entries:
                del self.entries[next(iter(self.entries))]
            self.entries[key] = (value, monotonic() + self.ttl_seconds)
            return value, "MISS"

    def invalidate(self, key):
        with self.lock:
            self.entries.pop(key, None)

    def clear(self):
        with self.lock:
            self.entries.clear()


class FixedWindowLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.counters = {}
        self.lock = Lock()

    def check(self, client_ip: str):
        with self.lock:
            window = int(time() // self.window_seconds)
            expired = [ip for ip, (saved_window, _) in self.counters.items() if saved_window != window]
            for ip in expired:
                del self.counters[ip]
            _, count = self.counters.get(client_ip, (window, 0))
            allowed = count < self.limit
            if allowed:
                count += 1
                self.counters[client_ip] = (window, count)
            return allowed, {
                "X-RateLimit-Limit": str(self.limit),
                "X-RateLimit-Remaining": str(self.limit - count),
                "X-RateLimit-Reset": str((window + 1) * self.window_seconds),
            }

    def clear(self):
        with self.lock:
            self.counters.clear()


folder_cache = TTLCache(ttl_seconds=30)
message_cache = TTLCache(ttl_seconds=15)
login_limiter = FixedWindowLimiter(limit=10, window_seconds=60)
