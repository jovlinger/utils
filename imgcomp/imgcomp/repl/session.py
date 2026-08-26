"""Edit-eval-draw session over imgcomp with optional quadtree cache."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

from imgcomp.naive import NaiveCompositor
from imgcomp.quad_cache import QuadCache
from imgcomp.shape import Shape
from imgcomp.repl.api_v0 import api_namespace
from imgcomp.rgba import RGBA, TRANSPARENT
from imgcomp.scene import Scene, as_z_list
from imgcomp.surface import Surface


@dataclass
class EvalResult:
    """Outcome of one REPL line."""

    ok: bool
    error: Optional[str] = None
    value: Any = None


@dataclass
class ReplSession:
    """Restricted Python exec loop bound to an imgcomp scene.

    Caching is off by default (single-shot evals). Pass ``use_cache=True`` on
    ``render`` for animation-style reuse via the compositor quadtree cache.
    """

    width: int
    height: int
    scene: Scene = field(default_factory=list)
    last_error: Optional[str] = None
    _bindings: Dict[str, Any] = field(default_factory=dict)
    _naive: Optional[NaiveCompositor] = None
    _cached: Optional[NaiveCompositor] = None

    def __post_init__(self) -> None:
        self._naive = NaiveCompositor(self.width, self.height, cache=False)
        self._cached = NaiveCompositor(self.width, self.height, cache=True)
        self._reset_bindings()

    def _reset_bindings(self) -> None:
        ns: Dict[str, Any] = api_namespace()
        ns["W"] = self.width
        ns["H"] = self.height
        ns["scene"] = self.scene
        ns["show"] = self.show
        ns["add"] = self.add
        ns["clear"] = self.clear_scene
        ns["pick"] = self.pick_name
        ns["sample"] = self.sample_rgba
        for key, value in self._bindings.items():
            if key not in ns:
                ns[key] = value
        self._bindings = ns

    @property
    def cache(self) -> Optional[QuadCache]:
        """Quadtree cache used when ``render(use_cache=True)``."""
        assert self._cached is not None
        return self._cached.cache

    def show(self, *shapes: Shape) -> None:
        self.scene = list(shapes)
        self._bindings["scene"] = self.scene

    def add(self, shape: Shape) -> None:
        layers = list(as_z_list(self.scene))
        layers.append(shape)
        self.scene = layers
        self._bindings["scene"] = self.scene

    def clear_scene(self) -> None:
        self.scene = []
        self._bindings["scene"] = self.scene

    def run_line(self, source: str) -> EvalResult:
        """Exec one line/block. On failure, keep prior scene and record error."""
        local_ns = self._bindings
        try:
            try:
                value = eval(source, {"__builtins__": {}}, local_ns)
                self._sync_scene_from_ns(local_ns)
                self.last_error = None
                return EvalResult(ok=True, value=value)
            except SyntaxError:
                exec(source, {"__builtins__": {}}, local_ns)
                self._sync_scene_from_ns(local_ns)
                self.last_error = None
                return EvalResult(ok=True, value=None)
        except Exception as exc:  # noqa: BLE001 -- REPL must catch learner errors
            message = f"{type(exc).__name__}: {exc}"
            self.last_error = message
            return EvalResult(ok=False, error=message)

    def _sync_scene_from_ns(self, ns: Dict[str, Any]) -> None:
        if "scene" in ns:
            self.scene = ns["scene"]
        reserved = set(api_namespace()) | {
            "W",
            "H",
            "scene",
            "show",
            "add",
            "clear",
            "pick",
            "sample",
        }
        for key, value in list(ns.items()):
            if key in reserved or key.startswith("_"):
                continue
            self._bindings[key] = value

    def render(self, *, use_cache: bool = False) -> Surface:
        comp = self._cached if use_cache else self._naive
        assert comp is not None
        return comp.render(self.scene)

    def pick_name(self, vx: float, vy: float) -> Optional[str]:
        assert self._naive is not None
        picked = self._naive.pick(self.scene, vx, vy)
        if picked is None:
            return None
        target = picked.target
        for name, value in self._bindings.items():
            if isinstance(value, Shape) and (
                value is target or _contains_object(value, target)
            ):
                return name
        return None

    def sample_rgba(self, vx: float, vy: float) -> RGBA:
        surface = self.render(use_cache=False)
        x = int(vx)
        y = int(vy)
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return TRANSPARENT
        return surface.get_pixel(x, y)


def _contains_object(root: Shape, target: Shape) -> bool:
    if root is target:
        return True
    child = getattr(root, "child", None)
    if isinstance(child, Shape) and _contains_object(child, target):
        return True
    members = getattr(root, "members", None)
    if isinstance(members, Sequence):
        for member in members:
            if isinstance(member, Shape) and _contains_object(member, target):
                return True
    return False
