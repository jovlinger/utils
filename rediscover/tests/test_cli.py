"""Unit tests for the rediscover CLI using Click's test runner and fakeredis."""

from __future__ import annotations

import csv
import io
import json
import threading
from unittest.mock import patch, MagicMock

import fakeredis
import pytest
from click.testing import CliRunner

from rediscover.cli import cli
from rediscover.client import RedisDiscoverClient


def _fake_server():
    return fakeredis.FakeServer()


def _make_patched_client(srv, namespace="default"):
    """Return a real RedisDiscoverClient wired to a FakeRedis server."""
    conn = fakeredis.FakeRedis(server=srv)
    client = RedisDiscoverClient.__new__(RedisDiscoverClient)
    client._namespace = namespace
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


def _invoke(args, client):
    """Invoke CLI with a pre-built client injected via patch."""
    runner = CliRunner()
    with patch("rediscover.cli._make_client", return_value=client):
        result = runner.invoke(cli, args)
    return result


class TestQueryEmpty:
    def test_query_empty(self):
        srv = _fake_server()
        client = _make_patched_client(srv)
        result = _invoke(["query"], client)
        assert result.exit_code == 0
        assert "No data" in result.output

        client.close()


class TestQueryWithData:
    def test_query_with_data(self):
        srv = _fake_server()
        client = _make_patched_client(srv)

        client.increment("some_function", count=42, elapsed_ms=1234.0)
        client.flush()

        result = _invoke(["query"], client)
        assert result.exit_code == 0
        assert "some_function" in result.output
        assert "42" in result.output

        client.close()


class TestResetAll:
    def test_reset_all(self):
        srv = _fake_server()
        client = _make_patched_client(srv)

        client.increment("fn_a", count=10)
        client.increment("fn_b", count=20)
        client.flush()

        result = _invoke(["reset"], client)
        assert result.exit_code == 0
        assert "Reset all" in result.output

        # Verify empty after reset.
        assert client.query() == {}

        client.close()


class TestResetSpecific:
    def test_reset_specific(self):
        srv = _fake_server()
        client = _make_patched_client(srv)

        client.increment("fn_a", count=10)
        client.increment("fn_b", count=20)
        client.flush()

        result = _invoke(["reset", "fn_a"], client)
        assert result.exit_code == 0
        assert "Reset: fn_a" in result.output

        data = client.query()
        assert "fn_a" not in data
        assert data["fn_b"]["calls"] == 20

        client.close()


class TestExportJson:
    def test_export_json(self):
        srv = _fake_server()
        client = _make_patched_client(srv)

        client.increment("fn_x", count=7, elapsed_ms=70.0)
        client.flush()

        result = _invoke(["export", "--format", "json"], client)
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert "fn_x" in data
        assert data["fn_x"]["calls"] == 7

        client.close()


class TestExportCsv:
    def test_export_csv(self):
        srv = _fake_server()
        client = _make_patched_client(srv)

        client.increment("fn_y", count=3, elapsed_ms=30.0)
        client.flush()

        result = _invoke(["export", "--format", "csv"], client)
        assert result.exit_code == 0

        reader = csv.DictReader(io.StringIO(result.output))
        rows = list(reader)
        assert any(row["name"] == "fn_y" and int(row["calls"]) == 3 for row in rows)

        client.close()
