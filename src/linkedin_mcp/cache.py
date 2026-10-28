"""A small in-memory cache with per-entry expiry."""

import time
from collections.abc import Awaitable, Callable, Hashable


class TTLCache[K: Hashable, V]:
    """In-memory cache whose entries expire a fixed time after they are stored.

    A TTL of 0 disables caching: every lookup loads the value again.
    """

    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic) -> None:
        """Create a cache.

        Args:
            ttl: Lifetime of an entry in seconds.
            clock: Function that returns the current time in seconds (for tests).
        """
        self._ttl = ttl
        self._clock = clock
        self._entries: dict[K, tuple[float, V]] = {}

    async def get_or_load(
        self, key: K, loader: Callable[[], Awaitable[V]], *, refresh: bool = False
    ) -> V:
        """Return the cached value for `key`, loading and storing it if needed.

        Args:
            key: Cache key.
            loader: Async function that produces the value on a cache miss.
            refresh: Ignore any cached value and load it again.

        Returns:
            The cached or newly loaded value.
        """
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and not refresh and now < entry[0]:
            return entry[1]
        value = await loader()
        self._entries[key] = (now + self._ttl, value)
        return value

    def invalidate(self, key: K) -> None:
        """Remove one entry, if present.

        Args:
            key: Cache key.
        """
        self._entries.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()
