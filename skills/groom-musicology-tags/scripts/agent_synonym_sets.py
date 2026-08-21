#!/usr/bin/env python3
"""Alternate synonym generator: vocab set → cheap linguistic agent → synonym sets.

Pipeline
--------
1. ``tag_vocab.py`` builds ``vocab.json`` (light normalize, no Porter stem).
2. This script batches surfaces and tasks a **cheap linguistic agent** to
   partition each batch into synonym sets (JSON).
3. ``merge`` folds agent responses into a reviewable map patch
   (``raw → type;value``) without overwriting existing maps by default.

Agent backends
--------------
- ``cursor`` (default for ``prepare``): write batch files + prompt; a Cursor
  agent (or human) fills ``responses/*.json``.
- ``openai``: OpenAI-compatible Chat Completions (``OPENAI_API_KEY``, model
  default ``gpt-4o-mini`` — override with ``--model`` / ``OPENAI_BASE_URL``).
- ``ollama``: local ``OLLAMA_HOST`` (default ``http://127.0.0.1:11434``).

The agent must return **only** JSON matching the schema in
``prompts/synonym-cluster-agent.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
DEFAULT_PROMPT = ROOT / "prompts" / "synonym-cluster-agent.md"
SHADUP = ROOT.parents[1] / "shadup"
for _p in (str(SCRIPTS), str(SHADUP)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tag_classify as tc  # noqa: E402
import tag_vocab as tv  # noqa: E402

PROVIDERS = ("discogs", "lastfm", "musicbrainz")


def load_vocab(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def batch_entries(entries: list[dict], *, size: int) -> list[list[dict]]:
    batches: list[list[dict]] = []
    for i in range(0, len(entries), size):
        batches.append(entries[i : i + size])
    return batches


def agent_system_prompt(prompt_path: Path) -> str:
    return prompt_path.read_text(encoding="utf-8")


def user_payload(batch_id: str, entries: list[dict]) -> str:
    surfaces = [
        {
            "id": i,
            "surface": e["surface"],
            "key": e["key"],
            "count": e["count"],
            "variants": [v["raw"] for v in e["variants"][:8]],
        }
        for i, e in enumerate(entries)
    ]
    return json.dumps(
        {
            "batch_id": batch_id,
            "instruction": (
                "Partition these music tags into synonym sets. "
                "Return JSON only per system schema."
            ),
            "tags": surfaces,
        },
        ensure_ascii=False,
        indent=2,
    )


def prepare_batches(
    vocab: dict,
    out_dir: Path,
    *,
    batch_size: int,
    prompt_path: Path,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "responses").mkdir(exist_ok=True)
    entries = vocab["entries"]
    batches = batch_entries(entries, size=batch_size)
    manifest = []
    for i, batch in enumerate(batches):
        batch_id = f"batch-{i:03d}"
        path = out_dir / f"{batch_id}.json"
        path.write_text(user_payload(batch_id, batch) + "\n", encoding="utf-8")
        manifest.append({"batch_id": batch_id, "path": path.name, "n": len(batch)})
    (out_dir / "manifest.json").write_text(
        json.dumps({"batches": manifest, "prompt": str(prompt_path)}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    # Convenience copy of prompt beside batches
    (out_dir / "PROMPT.md").write_text(
        agent_system_prompt(prompt_path), encoding="utf-8"
    )
    readme = out_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Agent synonym batches",
                "",
                "For each `batch-*.json`, ask a cheap linguistic model/agent",
                "using `PROMPT.md` as system instructions and the batch JSON as",
                "the user message. Write the model JSON to",
                f"`responses/<batch_id>.json` (e.g. `responses/batch-000.json`).",
                "",
                "Then:",
                "```bash",
                "python3 skills/groom-musicology-tags/scripts/agent_synonym_sets.py merge \\",
                f"  --vocab <vocab.json> --responses {out_dir}/responses --out <patch-dir>",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"prepared {len(batches)} batches → {out_dir}")
    return len(batches)


def _http_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_openai(system: str, user: str, *, model: str, base_url: str, api_key: str) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    doc = _http_json(url, body, headers)
    return doc["choices"][0]["message"]["content"]


def call_ollama(system: str, user: str, *, model: str, host: str) -> str:
    url = host.rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    doc = _http_json(url, body, {"Content-Type": "application/json"})
    return doc["message"]["content"]


def parse_agent_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        # fence strip
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def run_backend(
    batches_dir: Path,
    *,
    backend: str,
    model: str,
    prompt_path: Path,
) -> int:
    system = agent_system_prompt(prompt_path)
    resp_dir = batches_dir / "responses"
    resp_dir.mkdir(exist_ok=True)
    manifest = json.loads((batches_dir / "manifest.json").read_text(encoding="utf-8"))
    n_ok = 0
    for row in manifest["batches"]:
        batch_id = row["batch_id"]
        user = (batches_dir / row["path"]).read_text(encoding="utf-8")
        out_path = resp_dir / f"{batch_id}.json"
        if out_path.is_file():
            print(f"skip existing {out_path.name}")
            n_ok += 1
            continue
        try:
            if backend == "openai":
                key = os.environ.get("OPENAI_API_KEY", "")
                if not key:
                    raise SystemExit("OPENAI_API_KEY not set")
                base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
                raw = call_openai(system, user, model=model, base_url=base, api_key=key)
            elif backend == "ollama":
                host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
                raw = call_ollama(system, user, model=model, host=host)
            else:
                raise SystemExit(f"backend {backend!r} cannot auto-run (use prepare)")
            doc = parse_agent_json(raw)
            if doc.get("batch_id") and doc["batch_id"] != batch_id:
                doc["batch_id"] = batch_id
            else:
                doc.setdefault("batch_id", batch_id)
            out_path.write_text(
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"wrote {out_path}")
            n_ok += 1
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
            print(f"FAIL {batch_id}: {e}", file=sys.stderr)
    return n_ok


def type_value_for_set(canonical: str, type_hint: Optional[str]) -> str:
    hint = (type_hint or "").strip().lower()
    if hint in tc.CANON_TYPES:
        if hint == "year":
            yv = tc.year_value(canonical)
            return f"year;{yv or tc.slug(canonical)}"
        if hint == "artist":
            return f"artist;{tc.artist_canonical(canonical) or tc.slug(canonical)}"
        return f"{hint};{tc.slug(canonical)}"
    mapped = tc.classify_raw(canonical)
    if mapped:
        return tc.canonicalize_tag(mapped) or mapped
    return f"genre;{tc.slug(canonical)}"


def merge_responses(
    vocab: dict,
    responses_dir: Path,
    *,
    synonyms_dir: Path,
    force_mapped: bool,
) -> dict:
    """Fold agent synonym sets into map_patch + review report."""
    key_to_entry = {e["key"]: e for e in vocab["entries"]}
    surface_to_key = {}
    for e in vocab["entries"]:
        surface_to_key[e["surface"].casefold()] = e["key"]
        surface_to_key[e["key"]] = e["key"]
        for v in e["variants"]:
            surface_to_key[v["raw"].casefold()] = e["key"]
            surface_to_key[tv.surface_key(v["raw"])] = e["key"]

    sets_out: list[dict] = []
    dropped: list[str] = []
    singletons: list[str] = []

    for path in sorted(responses_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for s in doc.get("sets") or []:
            members = list(s.get("members") or [])
            canonical = s.get("canonical") or (members[0] if members else "")
            if not members:
                continue
            sets_out.append(
                {
                    "canonical": canonical,
                    "members": members,
                    "type_hint": s.get("type_hint"),
                    "note": s.get("note"),
                    "source": path.name,
                }
            )
        dropped.extend(doc.get("dropped") or [])
        singletons.extend(doc.get("singletons") or [])

    existing = {}
    for prov in PROVIDERS:
        p = synonyms_dir / f"{prov}.json"
        if p.is_file():
            existing[prov] = dict(
                json.loads(p.read_text(encoding="utf-8")).get("map") or {}
            )
        else:
            existing[prov] = {}

    map_patch: dict[str, dict[str, str]] = {p: {} for p in PROVIDERS}
    unresolved: list[str] = []

    for s in sets_out:
        proposed = type_value_for_set(s["canonical"], s.get("type_hint"))
        s["proposed"] = proposed
        for member in s["members"]:
            k = surface_to_key.get(member.casefold()) or surface_to_key.get(
                tv.surface_key(member)
            )
            if k is None:
                unresolved.append(member)
                continue
            entry = key_to_entry[k]
            for variant in entry["variants"]:
                raw = variant["raw"]
                for prov in entry["providers"]:
                    if prov not in PROVIDERS:
                        continue
                    cur = existing[prov].get(raw)
                    if cur is None or (force_mapped and cur != proposed):
                        if cur != proposed:
                            map_patch[prov][raw] = proposed

    map_patch = {p: m for p, m in map_patch.items() if m}

    return {
        "stats": {
            "sets": len(sets_out),
            "dropped": len(dropped),
            "singletons": len(singletons),
            "unresolved_members": len(unresolved),
            "patch_keys": sum(len(m) for m in map_patch.values()),
        },
        "sets": sets_out,
        "dropped": sorted(set(dropped)),
        "singletons": sorted(set(singletons)),
        "unresolved_members": sorted(set(unresolved)),
        "map_patch": map_patch,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    prep = sub.add_parser("prepare", help="Write batch JSON + PROMPT for an agent")
    prep.add_argument("--vocab", type=Path, required=True)
    prep.add_argument("--out", type=Path, required=True, help="batches directory")
    prep.add_argument("--batch-size", type=int, default=80)
    prep.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)

    run = sub.add_parser("run", help="Call openai/ollama on prepared batches")
    run.add_argument("--batches", type=Path, required=True)
    run.add_argument("--backend", choices=("openai", "ollama"), required=True)
    run.add_argument(
        "--model",
        default="",
        help="Default: gpt-4o-mini (openai) or llama3.2 (ollama)",
    )
    run.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)

    merge = sub.add_parser("merge", help="Merge responses/ into map_patch")
    merge.add_argument("--vocab", type=Path, required=True)
    merge.add_argument("--responses", type=Path, required=True)
    merge.add_argument("--out", type=Path, required=True)
    merge.add_argument(
        "--synonyms-dir",
        type=Path,
        default=ROOT / "synonyms",
    )
    merge.add_argument("--force-mapped", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "prepare":
        vocab = load_vocab(args.vocab)
        prepare_batches(
            vocab, args.out, batch_size=args.batch_size, prompt_path=args.prompt
        )
        return 0

    if args.cmd == "run":
        model = args.model or (
            "gpt-4o-mini" if args.backend == "openai" else "llama3.2"
        )
        n = run_backend(
            args.batches, backend=args.backend, model=model, prompt_path=args.prompt
        )
        print(f"completed {n} batch responses")
        return 0

    if args.cmd == "merge":
        vocab = load_vocab(args.vocab)
        doc = merge_responses(
            vocab,
            args.responses,
            synonyms_dir=args.synonyms_dir,
            force_mapped=args.force_mapped,
        )
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "agent_sets.json").write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (args.out / "map_patch.json").write_text(
            json.dumps(doc["map_patch"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"stats={doc['stats']} → {args.out}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
