"""Stacklang render parity with naive compositor."""

from __future__ import annotations

from imgcomp.compound import Intersect, Union
from imgcomp.naive import NaiveCompositor
from imgcomp.shapes import Circle, Rectangle, Rectangle
from imgcomp.stacklang_render import render
from imgcomp.wrappers import Color, Translate


def test_stacklang_matches_naive_union_scene() -> None:
    scene = [
        Union(
            Color(Translate(Circle(5.0), 8.0, 0.0), (255, 0, 0, 255)),
            Color(Translate(Circle(5.0), -8.0, 0.0), (0, 255, 0, 255)),
        )
    ]
    width = height = 40
    naive = NaiveCompositor(width, height).render(scene)
    stacklang = render(scene, width, height)
    assert naive.to_bytes() == stacklang.to_bytes()


def test_stacklang_matches_naive_intersect_scene() -> None:
    scene = [Color(Intersect(Circle(5.0), Rectangle(3.0, 3.0)), (255, 255, 0, 255))]
    width = height = 20
    naive = NaiveCompositor(width, height).render(scene)
    stacklang = render(scene, width, height)
    assert naive.to_bytes() == stacklang.to_bytes()
