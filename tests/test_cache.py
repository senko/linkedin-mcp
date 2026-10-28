from collections.abc import Awaitable, Callable

from linkedin_mcp.cache import TTLCache


class FakeClock:
    """A manually advanced clock."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def counting_loader(prefix: str = "value") -> tuple[Callable[[], Awaitable[str]], list[int]]:
    """Build a loader that returns a new value on each call, and its call log."""
    calls: list[int] = []

    async def load() -> str:
        calls.append(len(calls) + 1)
        return f"{prefix}-{len(calls)}"

    return load, calls


async def test_returns_cached_value_within_ttl() -> None:
    clock = FakeClock()
    cache: TTLCache[str, str] = TTLCache(10, clock)
    load, calls = counting_loader()

    assert await cache.get_or_load("key", load) == "value-1"
    clock.now = 9.9
    assert await cache.get_or_load("key", load) == "value-1"
    assert len(calls) == 1


async def test_reloads_after_ttl() -> None:
    clock = FakeClock()
    cache: TTLCache[str, str] = TTLCache(10, clock)
    load, _calls = counting_loader()

    await cache.get_or_load("key", load)
    clock.now = 10
    assert await cache.get_or_load("key", load) == "value-2"


async def test_refresh_forces_reload() -> None:
    cache: TTLCache[str, str] = TTLCache(10, FakeClock())
    load, _calls = counting_loader()

    await cache.get_or_load("key", load)
    assert await cache.get_or_load("key", load, refresh=True) == "value-2"
    assert await cache.get_or_load("key", load) == "value-2"


async def test_zero_ttl_disables_caching() -> None:
    cache: TTLCache[str, str] = TTLCache(0, FakeClock())
    load, calls = counting_loader()

    await cache.get_or_load("key", load)
    await cache.get_or_load("key", load)
    assert len(calls) == 2


async def test_keys_are_independent() -> None:
    cache: TTLCache[str | None, str] = TTLCache(10, FakeClock())
    load_a, _ = counting_loader("a")
    load_b, _ = counting_loader("b")

    assert await cache.get_or_load(None, load_a) == "a-1"
    assert await cache.get_or_load("other", load_b) == "b-1"
    assert await cache.get_or_load(None, load_b) == "a-1"


async def test_invalidate_removes_one_entry() -> None:
    cache: TTLCache[str, str] = TTLCache(10, FakeClock())
    load, _calls = counting_loader()
    await cache.get_or_load("a", load)
    await cache.get_or_load("b", load)

    cache.invalidate("a")
    cache.invalidate("missing")

    assert await cache.get_or_load("a", load) == "value-3"
    assert await cache.get_or_load("b", load) == "value-2"


async def test_clear_removes_all_entries() -> None:
    cache: TTLCache[str, str] = TTLCache(10, FakeClock())
    load, calls = counting_loader()
    await cache.get_or_load("a", load)
    await cache.get_or_load("b", load)

    cache.clear()
    await cache.get_or_load("a", load)
    await cache.get_or_load("b", load)

    assert len(calls) == 4
