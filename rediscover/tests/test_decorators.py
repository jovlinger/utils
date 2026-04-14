"""Unit tests for @count and @profile decorators."""

from __future__ import annotations

import threading
import time

import fakeredis
import pytest

from rediscover.client import RedisDiscoverClient
from rediscover.decorators import count, profile


def _make_client(srv=None):
    """Return a RedisDiscoverClient backed by a fakeredis server."""
    if srv is None:
        srv = fakeredis.FakeServer()
    conn = fakeredis.FakeRedis(server=srv)

    client = RedisDiscoverClient.__new__(RedisDiscoverClient)
    client._namespace = "test"
    client._flush_interval = 60.0
    client._flush_threshold = 1000
    client._connections = [conn]
    client._local_batch = {}
    client._lock = threading.Lock()
    client._stop_event = threading.Event()
    client._flush_thread = threading.Thread(
        target=client._flush_loop, daemon=True, name="rediscover-flush"
    )
    client._flush_thread.start()
    return client


class TestCountDecorator:
    def test_count_decorator(self):
        client = _make_client()

        @count(name="counter_test", client=client)
        def my_func():
            return 42

        for _ in range(5):
            my_func()

        client.flush()
        result = client.query()
        assert result["counter_test"]["calls"] == 5

        client.close()


class TestProfileDecorator:
    def test_profile_decorator(self):
        client = _make_client()

        @profile(name="profile_test", client=client)
        def slow_func():
            time.sleep(0.02)

        slow_func()
        client.flush()
        result = client.query()

        assert result["profile_test"]["calls"] == 1
        assert result["profile_test"]["time_ms"] > 0

        client.close()


class TestCountWithException:
    def test_count_with_exception(self):
        client = _make_client()

        @count(name="exc_test", client=client)
        def boom():
            raise ValueError("oops")

        for _ in range(3):
            try:
                boom()
            except ValueError:
                pass

        client.flush()
        result = client.query()
        assert result["exc_test"]["calls"] == 3

        client.close()


class TestThreadSafety:
    def test_thread_safety(self):
        client = _make_client()

        @count(name="thread_test", client=client)
        def work():
            pass

        threads = [
            threading.Thread(target=lambda: [work() for _ in range(100)])
            for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        client.flush()
        result = client.query()
        assert result["thread_test"]["calls"] == 1000

        client.close()


class TestCustomName:
    def test_custom_name(self):
        client = _make_client()

        @profile(name="my.custom.metric", client=client)
        def func():
            pass

        func()
        client.flush()
        result = client.query()

        assert "my.custom.metric" in result
        assert result["my.custom.metric"]["calls"] == 1

        client.close()
