"""Management CLI for rediscover counters."""

from __future__ import annotations

import csv
import io
import json
import sys
import time

import click

from rediscover.client import RedisDiscoverClient


def _make_client(redis_urls, namespace):
    return RedisDiscoverClient(list(redis_urls), namespace=namespace)


def _safe_query(client: RedisDiscoverClient):
    """Run client.query(), returning an empty dict on connection errors."""
    try:
        return client.query()
    except Exception as exc:
        click.echo(f"Error querying Redis: {exc}", err=True)
        return {}


def _print_table(data: dict) -> None:
    """Print counter data as a formatted table."""
    header = f"{'NAME':<40} {'CALLS':>8} {'TIME_MS':>10} {'AVG_MS':>8}"
    click.echo(header)
    click.echo("-" * len(header))
    rows = sorted(data.items(), key=lambda kv: kv[1].get("calls", 0), reverse=True)
    for name, metrics in rows:
        calls = metrics.get("calls", 0)
        time_ms = metrics.get("time_ms", 0)
        avg_ms = round(time_ms / calls, 1) if calls else 0.0
        click.echo(f"{name:<40} {calls:>8} {time_ms:>10} {avg_ms:>8}")


@click.group()
@click.option(
    "--redis",
    "redis_urls",
    multiple=True,
    default=["redis://localhost:6379"],
    show_default=True,
    help="Redis URL (repeat for multiple instances).",
)
@click.option("--namespace", default="default", show_default=True, help="Key namespace.")
@click.pass_context
def cli(ctx, redis_urls, namespace):
    """rediscover — manage distributed call counters stored in Redis."""
    ctx.ensure_object(dict)
    ctx.obj["redis_urls"] = redis_urls
    ctx.obj["namespace"] = namespace


@cli.command()
@click.pass_context
def query(ctx):
    """Display current counters sorted by call count."""
    client = _make_client(ctx.obj["redis_urls"], ctx.obj["namespace"])
    try:
        data = _safe_query(client)
        if not data:
            click.echo("No data.")
            return
        _print_table(data)
    finally:
        client.close()


@cli.command()
@click.argument("name", required=False, default=None)
@click.pass_context
def reset(ctx, name):
    """Reset counters for NAME, or all counters if NAME is omitted."""
    client = _make_client(ctx.obj["redis_urls"], ctx.obj["namespace"])
    try:
        client.reset(name)
        if name:
            click.echo(f"Reset: {name}")
        else:
            click.echo("Reset all")
    finally:
        client.close()


@cli.command()
@click.option("--interval", default=2, show_default=True, help="Refresh interval in seconds.")
@click.pass_context
def watch(ctx, interval):
    """Continuously display counters, refreshing every INTERVAL seconds."""
    client = _make_client(ctx.obj["redis_urls"], ctx.obj["namespace"])
    try:
        while True:
            click.clear()
            data = _safe_query(client)
            if not data:
                click.echo("No data.")
            else:
                _print_table(data)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()


@cli.command("export")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "csv"], case_sensitive=False),
    default="json",
    show_default=True,
    help="Output format.",
)
@click.pass_context
def export_cmd(ctx, fmt):
    """Export counters as JSON or CSV to stdout."""
    client = _make_client(ctx.obj["redis_urls"], ctx.obj["namespace"])
    try:
        data = _safe_query(client)
        if fmt == "json":
            click.echo(json.dumps(data, indent=2))
        else:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["name", "calls", "time_ms", "avg_ms"])
            for name, metrics in sorted(data.items()):
                calls = metrics.get("calls", 0)
                time_ms = metrics.get("time_ms", 0)
                avg_ms = round(time_ms / calls, 4) if calls else 0.0
                writer.writerow([name, calls, time_ms, avg_ms])
            click.echo(buf.getvalue(), nl=False)
    finally:
        client.close()
