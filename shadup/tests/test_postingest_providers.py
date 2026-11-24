"""postingest provider defaults must include local cue/txt."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

POSTINGEST = Path(__file__).resolve().parent.parent / "postingest"


def _load_postingest() -> object:
    # Extensionless script; SourceFileLoader is required.
    loader = importlib.machinery.SourceFileLoader("postingest_mod", str(POSTINGEST))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_configured_default_providers_include_cue_txt(monkeypatch) -> None:
    mod = _load_postingest()
    monkeypatch.delenv("POSTINGEST_PROVIDERS", raising=False)
    monkeypatch.delenv("DISCOGS_USER_TOKEN", raising=False)
    monkeypatch.delenv("DISCOGS_TOKEN", raising=False)
    monkeypatch.delenv("DISCOGS_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("DISCOGS_CONSUMER_SECRET", raising=False)
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    providers = mod.configured_default_providers()
    assert providers[0] == "musicbrainz"
    assert "cue" in providers
    assert "txt" in providers


def test_ensure_local_providers_appends_missing() -> None:
    mod = _load_postingest()
    assert mod.ensure_local_providers(["musicbrainz"]) == [
        "musicbrainz",
        "cue",
        "txt",
    ]
    assert mod.ensure_local_providers(["musicbrainz", "cue", "txt"]) == [
        "musicbrainz",
        "cue",
        "txt",
    ]


def test_known_providers_include_local() -> None:
    mod = _load_postingest()
    assert "cue" in mod.KNOWN_PROVIDERS
    assert "txt" in mod.KNOWN_PROVIDERS
