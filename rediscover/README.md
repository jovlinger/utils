# rediscover

Lightweight line-hotspot profiling for Python using `sys.settrace`.

The single question this project targets is:

> Which Python source line executes most often?

## How to run your program with line tracing

Use Python's built-in `trace` module (it uses `sys.settrace` under the hood):

```bash
python -m trace --count --file .disttrace.counts path/to/your_program.py [args...]
```

For package/module entrypoints:

```bash
python -m trace --count --file .disttrace.counts -m your_package.your_module [args...]
```

This writes execution counts to `.disttrace.counts`.

## Report the hottest line

Generate a readable report:

```bash
python -m trace --report --file .disttrace.counts > .disttrace.report.txt
```

Open `.disttrace.report.txt` and look for the largest count value.  
That row is the most frequently executed line.

## Useful workflow

```bash
# 1) Remove old profile data
rm -f .disttrace.counts .disttrace.report.txt

# 2) Run your real workload under tracing
python -m trace --count --file .disttrace.counts -m your_package.main -- --your --args

# 3) Build report
python -m trace --report --file .disttrace.counts > .disttrace.report.txt
```

## Notes

- `trace` adds overhead; run representative but bounded workloads.
- For stable comparisons, keep the same input and runtime flags between runs.
- If you only care about your own code, run from repo root and keep third-party work minimal in the profiled path.
