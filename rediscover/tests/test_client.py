"""Unit tests for RedisDiscoverClient using fakeredis."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import fakeredis
import pytest

from rediscover.client import RedisDiscoverClient


def _make_client(fake_servers, namespace="test", flush_interval=60.0, flush_threshold=1000):
    """Build a client backed by pre-created fakeredis server instances."""
    connections = [fakeredis.FakeRedis(server=srv) for srv in fake_servers]
    client = RedisDiscoverClient.__new__(RedisDiscoverClient)
    client._namespace = namespace
    client._flush_interval = flush_interval
    client._flush_threshold = flush_threshold
    client._connections = connections
    client._local_batch = {}
    client._lock = threading.Lock()
    client._stop_event = threading.Event()
    client._flush_thread = threading.Thread(
        target=client._flush_loop, daemon=True, name="rediscover-flush"
    )
    client._flush_thread.start()
    return client


class TestIncrementAndQuery:
    def test_increment_and_query(self):
        srv = fakeredis.FakeServer()
        client = _make_client([srv])

        client.increment("my_func", count=5, elapsed_ms=100.0)
        client.flush()

        result = client.query()
        assert "my_func" in result
        assert result["my_func"]["calls"] == 5
        assert result["my_func"]["time_ms"] == 100

        client.close()

    def test_increment_accumulates(self):
        srv = fakeredis.FakeServer()
        client = _make_client([srv])

        client.increment("fn", count=3, elapsed_ms=30.0)
        client.increment("fn", count=2, elapsed_ms=20.0)
        client.flush()

        result = client.query()
        assert result["fn"]["calls"] == 5
        assert result["fn"]["time_ms"] == 50

        client.close()


class TestMultiInstanceCollation:
    def test_multi_instance_collation(self):
        srv1 = fakeredis.FakeServer()
        srv2 = fakeredis.FakeServer()

        # Manually seed different counts into each instance.
        conn1 = fakeredis.FakeRedis(server=srv1)
        conn2 = fakeredis.FakeRedis(server=srv2)
        conn1.incrby("rediscover:test:fn:calls", 10)
        conn1.incrby("rediscover:test:fn:time_ms", 200)
        conn2.incrby("rediscover:test:fn:calls", 5)
        conn2.incrby("rediscover:test:fn:time_ms", 100)

        client = _make_client([srv1, srv2])
        result = client.query()

        assert result["fn"]["calls"] == 15
        assert result["fn"]["time_ms"] == 300

        client.close()


class TestReset:
    def test_reset_specific(self):
        srv = fakeredis.FakeServer()
        client = _make_client([srv])

        client.increment("fn_a", count=3)
        client.increment("fn_b", count=7)
        client.flush()

        client.reset("fn_a")

        result = client.query()
        assert "fn_a" not in result
        assert result["fn_b"]["calls"] == 7

        client.close()

    def test_reset_all(self):
        srv = fakeredis.FakeServer()
        client = _make_client([srv])

        client.increment("fn_a", count=3)
        client.increment("fn_b", count=7)
        client.flush()

        client.reset()

        result = client.query()
        assert result == {}

        client.close()


class TestBatchFlushOnThreshold:
    def test_batch_flush_on_threshold(self):
        srv = fakeredis.FakeServer()
        client = _make_client([srv], flush_threshold=4)

        # Each increment adds 2 keys (calls + time_ms); threshold=4 means 2 names.
        client.increment("fn_a", count=1, elapsed_ms=10.0)
        # Batch has 2 keys — below threshold.
        assert client._local_batch  # not yet flushed

        client.increment("fn_b", count=1, elapsed_ms=10.0)
        # Batch now has 4 keys — triggers flush inside increment.
        time.sleep(0.05)  # allow flush to propagate

        result = client.query()
        # Both names should be in Redis.
        assert "fn_a" in result
        assert "fn_b" in result

        client.close()
