"""TaskEvent base: binary / text / C-literal / form codecs."""

from __future__ import annotations

import struct
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Dict, List, Mapping, Tuple, Type, TypeVar
from urllib.parse import parse_qsl, urlencode

from . import constants as C

T = TypeVar("T", bound="TaskEvent")


class TaskEventError(ValueError):
    """Invalid TaskEvent encode/decode."""


class FormEncodeError(TaskEventError):
    """Event is not flat enough for application/x-www-form-urlencoded."""


def _pack_char_array(value: str, size: int) -> bytes:
    raw = value.encode("ascii", errors="strict")
    if len(raw) >= size:
        raise TaskEventError(f"string length {len(raw)} >= char array {size}")
    return raw + b"\x00" * (size - len(raw))


def _unpack_char_array(buf: bytes) -> str:
    nul = buf.find(b"\x00")
    if nul < 0:
        raw = buf
    else:
        raw = buf[:nul]
    return raw.decode("ascii", errors="strict")


def _c_escape(s: str) -> str:
    out: List[str] = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif 32 <= o < 127:
            out.append(ch)
        else:
            out.append(f"\\x{o:02x}")
    return "".join(out)


@dataclass(frozen=True)
class FieldSpec:
    """One body field in declaration order (matches C struct member order)."""

    name: str
    kind: str  # u8 u16 u32 i8 i16 i32 char bytes
    size: int = 0  # char/bytes capacity; length companion for bytes via length_field
    length_field: str = ""  # for bytes: name of u16/u8 length field
    flat: bool = True  # False => form encode fails
    c_name: str = ""  # C member name when different from Python attr

    @property
    def c_member(self) -> str:
        return self.c_name or self.name
    def pack(self, value: Any, values: Mapping[str, Any]) -> bytes:
        if self.kind == "u8":
            return struct.pack("<B", int(value) & 0xFF)
        if self.kind == "u16":
            return struct.pack("<H", int(value) & 0xFFFF)
        if self.kind == "u32":
            return struct.pack("<I", int(value) & 0xFFFFFFFF)
        if self.kind == "i8":
            return struct.pack("<b", int(value))
        if self.kind == "i16":
            return struct.pack("<h", int(value))
        if self.kind == "i32":
            return struct.pack("<i", int(value))
        if self.kind == "char":
            return _pack_char_array(str(value), self.size)
        if self.kind == "bytes":
            data = bytes(value) if not isinstance(value, bytes) else value
            n = int(values[self.length_field])
            if len(data) != n:
                raise TaskEventError(
                    f"{self.name}: len {len(data)} != {self.length_field}={n}"
                )
            if n > self.size:
                raise TaskEventError(f"{self.name}: n {n} > max {self.size}")
            return data + b"\x00" * (self.size - n)
        raise TaskEventError(f"unknown field kind {self.kind}")

    def unpack(self, data: bytes, offset: int, acc: Dict[str, Any]) -> Tuple[Any, int]:
        if self.kind == "u8":
            (v,) = struct.unpack_from("<B", data, offset)
            return v, offset + 1
        if self.kind == "u16":
            (v,) = struct.unpack_from("<H", data, offset)
            return v, offset + 2
        if self.kind == "u32":
            (v,) = struct.unpack_from("<I", data, offset)
            return v, offset + 4
        if self.kind == "i8":
            (v,) = struct.unpack_from("<b", data, offset)
            return v, offset + 1
        if self.kind == "i16":
            (v,) = struct.unpack_from("<h", data, offset)
            return v, offset + 2
        if self.kind == "i32":
            (v,) = struct.unpack_from("<i", data, offset)
            return v, offset + 4
        if self.kind == "char":
            chunk = data[offset : offset + self.size]
            if len(chunk) != self.size:
                raise TaskEventError(f"short read on {self.name}")
            return _unpack_char_array(chunk), offset + self.size
        if self.kind == "bytes":
            chunk = data[offset : offset + self.size]
            if len(chunk) != self.size:
                raise TaskEventError(f"short read on {self.name}")
            n = int(acc[self.length_field])
            if n > self.size:
                raise TaskEventError(f"{self.name}: n {n} > max {self.size}")
            return chunk[:n], offset + self.size
        raise TaskEventError(f"unknown field kind {self.kind}")

    def text_dump(self, value: Any) -> str:
        if self.kind == "bytes":
            return bytes(value).hex()
        return str(value)

    def text_load(self, raw: str) -> Any:
        if self.kind in ("u8", "u16", "u32", "i8", "i16", "i32"):
            return int(raw, 0)
        if self.kind == "char":
            return raw
        if self.kind == "bytes":
            return bytes.fromhex(raw) if raw else b""
        raise TaskEventError(f"unknown field kind {self.kind}")

    def c_literal_part(self, value: Any) -> str:
        mem = self.c_member
        if self.kind == "char":
            return f'.{mem} = "{_c_escape(str(value))}"'
        if self.kind == "bytes":
            data = bytes(value)
            if not data:
                return f".{mem} = {{0}}"
            parts = ", ".join(f"0x{b:02x}" for b in data)
            return f".{mem} = {{{parts}}}"
        return f".{mem} = {int(value)}"

class TaskEvent:
    """Base class for typed TaskActor event bodies.

    Binary layout is packed little-endian fields in ``field_specs`` order
    (portable wire / ESP32-friendly). In-memory C structs may add padding;
    this codec is the normative on-wire body shape.
    """

    type_id: ClassVar[int]
    type_name: ClassVar[str]
    c_type_name: ClassVar[str]
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()

    def _values(self) -> Dict[str, Any]:
        if not is_dataclass(self):
            raise TypeError(f"{type(self).__name__} must be a @dataclass")
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def write_binary(self) -> bytes:
        values = self._values()
        parts: List[bytes] = []
        for spec in self.field_specs:
            parts.append(spec.pack(values[spec.name], values))
        return b"".join(parts)

    @classmethod
    def read_binary(cls: Type[T], data: bytes) -> T:
        offset = 0
        acc: Dict[str, Any] = {}
        for spec in cls.field_specs:
            val, offset = spec.unpack(data, offset, acc)
            acc[spec.name] = val
        if offset != len(data):
            raise TaskEventError(
                f"{cls.__name__}: trailing {len(data) - offset} bytes"
            )
        return cls(**acc)

    @classmethod
    def to_c_struct(cls: Type[T], **kwargs: Any) -> bytes:
        """Classmethod: pack kwargs into the packed LE C body representation."""
        return cls(**kwargs).write_binary()

    def write_text(self) -> str:
        lines = [
            f"event={self.type_name}",
            f"type_id={self.type_id}",
        ]
        values = self._values()
        for spec in self.field_specs:
            lines.append(f"{spec.name}={spec.text_dump(values[spec.name])}")
        return "\n".join(lines) + "\n"

    @classmethod
    def read_text(cls: Type[T], text: str) -> T:
        mapping: Dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise TaskEventError(f"bad text line: {line!r}")
            k, v = line.split("=", 1)
            mapping[k] = v
        if "event" in mapping and mapping["event"] != cls.type_name:
            raise TaskEventError(
                f"expected event={cls.type_name}, got {mapping['event']}"
            )
        if "type_id" in mapping and int(mapping["type_id"], 0) != cls.type_id:
            raise TaskEventError(
                f"expected type_id={cls.type_id}, got {mapping['type_id']}"
            )
        kwargs: Dict[str, Any] = {}
        for spec in cls.field_specs:
            if spec.name not in mapping:
                raise TaskEventError(f"missing field {spec.name}")
            kwargs[spec.name] = spec.text_load(mapping[spec.name])
        return cls(**kwargs)

    def to_c_literal(self) -> str:
        """C compound-literal text for this body's value."""
        if not self.field_specs:
            return f"({self.c_type_name}){{0}}"
        values = self._values()
        parts = [spec.c_literal_part(values[spec.name]) for spec in self.field_specs]
        inner = ", ".join(parts)
        return f"({self.c_type_name}){{ {inner} }}"

    def is_flat(self) -> bool:
        return all(spec.flat for spec in self.field_specs)

    def to_form(self) -> str:
        """application/x-www-form-urlencoded; fails if not flat."""
        if not self.is_flat():
            raise FormEncodeError(f"{self.type_name} is not flat for form encoding")
        pairs: List[Tuple[str, str]] = [
            ("event", self.type_name),
            ("type_id", str(self.type_id)),
        ]
        values = self._values()
        for spec in self.field_specs:
            val = values[spec.name]
            if isinstance(val, (list, tuple)):
                for item in val:
                    pairs.append((spec.name, str(item)))
            else:
                pairs.append((spec.name, spec.text_dump(val)))
        return urlencode(pairs)

    @classmethod
    def from_form(cls: Type[T], data: str | bytes) -> T:
        if isinstance(data, bytes):
            data = data.decode("ascii")
        raw_pairs = parse_qsl(data, keep_blank_values=True)
        multi: Dict[str, List[str]] = {}
        for k, v in raw_pairs:
            multi.setdefault(k, []).append(v)
        if "event" in multi and multi["event"][-1] != cls.type_name:
            raise TaskEventError(
                f"expected event={cls.type_name}, got {multi['event'][-1]}"
            )
        if "type_id" in multi and int(multi["type_id"][-1], 0) != cls.type_id:
            raise TaskEventError(
                f"expected type_id={cls.type_id}, got {multi['type_id'][-1]}"
            )
        kwargs: Dict[str, Any] = {}
        for spec in cls.field_specs:
            if not spec.flat:
                raise FormEncodeError(f"{cls.type_name}.{spec.name} not form-flat")
            if spec.name not in multi:
                raise TaskEventError(f"missing form field {spec.name}")
            vals = multi[spec.name]
            if len(vals) == 1:
                kwargs[spec.name] = spec.text_load(vals[0])
            else:
                # Repeated keys -> list of parsed scalars (lists only).
                kwargs[spec.name] = [spec.text_load(v) for v in vals]
        return cls(**kwargs)


@dataclass
class EventEnvelope:
    """Queue slot: src + session + enqueue time + typed body."""

    src: str
    session_id: int
    enqueue_time_ms: int
    event: TaskEvent

    def write_binary(self) -> bytes:
        head = (
            _pack_char_array(self.src, C.TA_NAME_MAX)
            + struct.pack("<I", self.session_id & 0xFFFFFFFF)
            + struct.pack("<I", self.enqueue_time_ms & 0xFFFFFFFF)
            + struct.pack("<H", self.event.type_id & 0xFFFF)
        )
        return head + self.event.write_binary()

    @classmethod
    def read_binary(cls, data: bytes, registry: Mapping[int, Type[TaskEvent]]) -> "EventEnvelope":
        need = C.TA_NAME_MAX + 4 + 4 + 2
        if len(data) < need:
            raise TaskEventError("envelope truncated")
        src = _unpack_char_array(data[0 : C.TA_NAME_MAX])
        session_id, enqueue_time_ms, type_id = struct.unpack_from(
            "<IIH", data, C.TA_NAME_MAX
        )
        body_cls = registry.get(type_id)
        if body_cls is None:
            raise TaskEventError(f"unknown type_id {type_id:#x}")
        body = body_cls.read_binary(data[need:])
        return cls(
            src=src,
            session_id=session_id,
            enqueue_time_ms=enqueue_time_ms,
            event=body,
        )

    def write_text(self) -> str:
        return (
            f"src={self.src}\n"
            f"session_id={self.session_id}\n"
            f"enqueue_time_ms={self.enqueue_time_ms}\n"
            + self.event.write_text()
        )

    def to_c_literal(self) -> str:
        arm = _union_arm(self.event)
        if arm:
            u_part = f".u = {{ .{arm} = {self.event.to_c_literal()} }}"
        else:
            u_part = ".u = {0}"
        return (
            "(ta_event_envelope_t){ "
            f'.src = "{_c_escape(self.src)}", '
            f".session_id = {self.session_id}u, "
            f".enqueue_time_ms = {self.enqueue_time_ms}u, "
            f".event = {{ .type = {self.event.type_id}, {u_part} }} "
            "}"
        )


def _union_arm(ev: TaskEvent) -> str:
    arm = getattr(ev, "c_union_arm", None)
    if isinstance(arm, str):
        return arm
    name = ev.type_name
    out: List[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)
