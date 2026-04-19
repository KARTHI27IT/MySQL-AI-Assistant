"""
core/cache.py
In-memory schema cache with TTL-based expiry.
"""
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional

from config import MYSQL_CONFIG


class SchemaCache:
    """
    Thread-safe (single-process) in-memory cache for database schemas.
    Keyed by database name + connection fingerprint, with a configurable TTL.
    """

    def __init__(self, ttl_seconds: int = 600):
        self.cache: Dict[str, Dict] = {}
        self.timestamps: Dict[str, datetime] = {}
        self.ttl = timedelta(seconds=ttl_seconds)

    def _key(self, db: str) -> str:
        """Derive a unique cache key from the database name and connection host/user."""
        h = hashlib.md5(
            f"{MYSQL_CONFIG['host']}:{MYSQL_CONFIG['user']}".encode()
        ).hexdigest()[:8]
        return f"{db}:{h}"

    def get(self, db: str) -> Optional[Dict]:
        """Return cached schema if present and not expired, else None."""
        k = self._key(db)
        if k in self.cache and datetime.now() - self.timestamps[k] < self.ttl:
            return self.cache[k]
        self.cache.pop(k, None)
        self.timestamps.pop(k, None)
        return None

    def set(self, db: str, schema: Dict):
        """Store a schema in the cache with the current timestamp."""
        k = self._key(db)
        self.cache[k] = schema
        self.timestamps[k] = datetime.now()

    def invalidate(self, db: str):
        """Remove the cached schema for the given database."""
        k = self._key(db)
        self.cache.pop(k, None)
        self.timestamps.pop(k, None)


# Singleton instance used across the application
schema_cache = SchemaCache(ttl_seconds=600)