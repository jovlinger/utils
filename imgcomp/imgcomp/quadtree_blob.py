"""Read-only quadtree blob: flat CQuadNode array + leaf member op ids."""

from __future__ import annotations

import mmap
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from imgcomp.stacklang_render import QuadNode

MAGIC = 0x51545245  # QTRE
VERSION = 2
HEADER_STRUCT = struct.Struct("<4I")
NODE_STRUCT = struct.Struct("<4d2iB7x")
LEAF_OP_STRUCT = struct.Struct("<i")
HEADER_SIZE = HEADER_STRUCT.size
NODE_SIZE = NODE_STRUCT.size  # 48 bytes, 8-byte aligned nodes


def _flatten_node(
    node: QuadNode,
    flat: list[tuple[float, float, float, float, int, int, int]],
    leaf_ops: list[int],
) -> None:
    idx = len(flat)
    bounds = node.bounds
    if node.zlist is not None:
        zlist = node.zlist
        member_ops = [member.paint_op_id for member in zlist.members]
        offset = len(leaf_ops)
        leaf_ops.extend(member_ops)
        flat.append(
            (
                bounds.xmin,
                bounds.ymin,
                bounds.xmax,
                bounds.ymax,
                offset,
                -1,
                min(len(member_ops), 255),
            )
        )
        return
    flat.append((0.0, 0.0, 0.0, 0.0, -1, 0, 1))  # placeholder
    first_child = len(flat)
    assert node.children is not None
    for child in node.children:
        _flatten_node(child, flat, leaf_ops)
    flat[idx] = (
        bounds.xmin,
        bounds.ymin,
        bounds.xmax,
        bounds.ymax,
        -1,
        first_child,
        1,
    )


def serialize_quadtree(root: QuadNode) -> bytes:
    """Pack quadtree nodes and per-leaf member VM op ids into a binary blob."""
    nodes: list[tuple[float, float, float, float, int, int, int]] = []
    leaf_ops: list[int] = []
    _flatten_node(root, nodes, leaf_ops)
    buf = bytearray(HEADER_SIZE + NODE_SIZE * len(nodes) + LEAF_OP_STRUCT.size * len(leaf_ops))
    HEADER_STRUCT.pack_into(buf, 0, MAGIC, VERSION, len(nodes), len(leaf_ops))
    offset = HEADER_SIZE
    for node in nodes:
        NODE_STRUCT.pack_into(buf, offset, *node)
        offset += NODE_SIZE
    for op_id in leaf_ops:
        LEAF_OP_STRUCT.pack_into(buf, offset, op_id)
        offset += LEAF_OP_STRUCT.size
    return bytes(buf)


def mmap_quadtree(blob: bytes) -> mmap.mmap:
    """Map a serialized quadtree blob read-only for C traversal."""
    if len(blob) < HEADER_SIZE:
        raise ValueError("quadtree blob too small for header")
    magic, version, node_count, leaf_op_count = HEADER_STRUCT.unpack_from(blob, 0)
    if magic != MAGIC:
        raise ValueError(f"bad quadtree magic: {magic:#x}")
    if version != VERSION:
        raise ValueError(f"unsupported quadtree version: {version}")
    expected = HEADER_SIZE + NODE_SIZE * node_count + LEAF_OP_STRUCT.size * leaf_op_count
    if len(blob) != expected:
        raise ValueError(f"quadtree blob size mismatch: {len(blob)} != {expected}")
    mm = mmap.mmap(-1, len(blob))
    mm.write(blob)
    mm.seek(0)
    return mm
