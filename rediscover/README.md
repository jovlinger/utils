# rediscover

**Distributed counter-based profiling via Redis.**

`rediscover` lets you count function calls and record elapsed time across a fleet of processes, persisting metrics atomically to one or more Redis instances. A CLI lets you query, reset, watch, and export those counters.

---

## Purpose

Traditional profilers are per-process and ephemeral. `rediscover` is designed for *distributed* environments: every worker, web server, or background job increments the same shared counters in Redis. This answers questions like:

- Which functions are called most across all processes?
- How much cumulative time is spent in a given code path fleet-wide?
- Did a deploy change the hot path?

---

## Quick start

### 1. Install

```bash
pip install -e .           # from the rediscover/ directory
# or
pip install redis click
```

### 2. Configure and instrument

```python
import rediscover

# Point at one or more Redis instances.
rediscover.configure(
    ["redis://localhost:6379"],
    namespace="myapp",
)

@rediscover.profile(name="my_service.process_request")
def process_request(payload):
    ...

@rediscover.count(name="my_service.cache_hit")
def cache_hit():
    ...
```

### 3. Query via CLI

```bash
rediscover --redis redis://localhost:6379 --namespace myapp query
```

```
NAME                                     CALLS    TIME_MS    AVG_MS
my_service.process_request                 500      12340      24.7
my_service.cache_hit                       320          0       0.0
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Your application process                                        │
│                                                                  │
│  @profile / @count                                               │
│      │                                                           │
│      ▼                                                           │
│  RedisDiscoverClient._local_batch (dict, protected by Lock)      │
│      │                                                           │
│      │  flush every flush_interval seconds  OR                   │
│      │  when batch size ≥ flush_threshold                        │
│      ▼                                                           │
│  Redis pipeline  INCRBY  key delta                               │
└────────────────────┬────────────────────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
     Redis instance 1     Redis instance 2   (multi-instance)
```

Key design decisions:

- **Local batching**: increments are accumulated in a `dict` protected by a `threading.Lock`. No Redis round-trip per call.
- **Atomic INCRBY**: all batched increments are sent as a single pipeline of `INCRBY` commands. This is race-safe even when multiple processes write to the same key.
- **Multi-instance collation**: `query()` reads all configured Redis instances and sums counts. Each instance receives the same data over time, providing redundancy.
- **Daemon flush thread**: a background thread flushes on a configurable interval without blocking process exit.

### Key schema

```
rediscover:{namespace}:{name}:calls     → total call count  (integer)
rediscover:{namespace}:{name}:time_ms   → total elapsed ms  (integer)
```

---

## Auto-instrumentation

`rediscover.auto` provides dd-trace-style monkey-patching:

```python
import mymodule
from rediscover.auto import patch_module, unpatch_module

patch_module(mymodule)          # wraps all public callables with @profile
# ... run code ...
unpatch_module(mymodule)        # restores originals
```

Or for a class:

```python
from rediscover.auto import patch_class, unpatch_class
patch_class(MyService)
```

> **Alternative design note**: instead of our own collection layer, we could rely on dd-trace for tracing and implement a bespoke Datadog Agent that reads dd-trace spans and publishes counter/timing data to Redis. This would give richer trace context (distributed trace IDs, service topology) at the cost of a dd-trace dependency. The current implementation is self-contained and dependency-light.

---

## Running tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt
pip install -e .

# Run unit tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=rediscover --cov-report=term-missing
```

### E2E tests (requires Docker)

```bash
pip install -e .   # so the `rediscover` CLI is on PATH
bash e2e/run_e2e.sh
```

The E2E script:
1. Starts two Redis containers and the sample app via `docker compose`
2. Resets all counters
3. Sends HTTP requests to `/work`
4. Queries counters via the CLI and asserts expected values
5. Tears everything down and prints PASS / FAIL

---

## CLI reference

```
Usage: rediscover [OPTIONS] COMMAND [ARGS]...

  rediscover — manage distributed call counters stored in Redis.

Options:
  --redis TEXT       Redis URL (repeat for multiple instances).  [default: redis://localhost:6379]
  --namespace TEXT   Key namespace.  [default: default]

Commands:
  export   Export counters as JSON or CSV to stdout.
  query    Display current counters sorted by call count.
  reset    Reset counters for NAME, or all counters if NAME is omitted.
  watch    Continuously display counters, refreshing every INTERVAL seconds.
```

### `query`

```bash
rediscover --redis redis://host:6379 --namespace prod query
```

### `reset [NAME]`

```bash
rediscover --namespace prod reset my_func   # reset one counter
rediscover --namespace prod reset           # reset all
```

### `watch [--interval N]`

```bash
rediscover --namespace prod watch --interval 5
```

### `export --format json|csv`

```bash
rediscover --namespace prod export --format json > metrics.json
rediscover --namespace prod export --format csv  > metrics.csv
```
