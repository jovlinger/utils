"""Concrete TaskEvent subclasses (mirrors host/ta_event.h bodies)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Dict, List, Tuple, Type

from . import constants as C
from .base import FieldSpec, TaskEvent

def _char(name: str, size: int) -> FieldSpec:
    return FieldSpec(name=name, kind="char", size=size)


def _u8(name: str) -> FieldSpec:
    return FieldSpec(name=name, kind="u8")


def _u16(name: str) -> FieldSpec:
    return FieldSpec(name=name, kind="u16")


def _u32(name: str) -> FieldSpec:
    return FieldSpec(name=name, kind="u32")


def _i8(name: str) -> FieldSpec:
    return FieldSpec(name=name, kind="i8")


def _i16(name: str) -> FieldSpec:
    return FieldSpec(name=name, kind="i16")


def _i32(name: str) -> FieldSpec:
    return FieldSpec(name=name, kind="i32")


@dataclass
class Nop(TaskEvent):
    type_id: ClassVar[int] = C.TA_EV_NOP
    type_name: ClassVar[str] = "Nop"
    c_type_name: ClassVar[str] = "uint8_t"
    c_union_arm: ClassVar[str] = ""
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()


@dataclass
class LogEmitLine(TaskEvent):
    severity: int
    tag: int
    text: str

    type_id: ClassVar[int] = C.TA_EV_LOG
    type_name: ClassVar[str] = "LogEmitLine"
    c_type_name: ClassVar[str] = "ta_log_emit_line_t"
    c_union_arm: ClassVar[str] = "log_emit_line"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _u8("severity"),
        _u8("tag"),
        _char("text", C.TA_LOG_TEXT_MAX + 1),
    )


@dataclass
class CtrlSetRoute(TaskEvent):
    target: str

    type_id: ClassVar[int] = C.TA_EV_SET_ROUTE
    type_name: ClassVar[str] = "CtrlSetRoute"
    c_type_name: ClassVar[str] = "ta_ctrl_set_route_t"
    c_union_arm: ClassVar[str] = "ctrl_set_route"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_char("target", C.TA_NAME_MAX),)


@dataclass
class AllPerformInit(TaskEvent):
    unused: int = 0

    type_id: ClassVar[int] = C.TA_EV_ALL_PERFORM_INIT
    type_name: ClassVar[str] = "AllPerformInit"
    c_type_name: ClassVar[str] = "ta_all_perform_init_t"
    c_union_arm: ClassVar[str] = "all_perform_init"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_u8("unused"),)


@dataclass
class AllInformResult(TaskEvent):
    status: int
    key: str
    n: int
    payload: bytes

    type_id: ClassVar[int] = C.TA_EV_ALL_INFORM_RESULT
    type_name: ClassVar[str] = "AllInformResult"
    c_type_name: ClassVar[str] = "ta_all_inform_result_t"
    c_union_arm: ClassVar[str] = "all_inform_result"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _u8("status"),
        _char("key", C.TA_ALL_KEY_MAX),
        _u16("n"),
        FieldSpec(
            name="payload",
            kind="bytes",
            size=C.TA_ALL_INFORM_MAX,
            length_field="n",
            flat=False,
            c_name="bytes",
        ),
    )


@dataclass
class IsrTouch(TaskEvent):
    x: int
    y: int

    type_id: ClassVar[int] = C.TA_EV_ISR_TOUCH
    type_name: ClassVar[str] = "IsrTouch"
    c_type_name: ClassVar[str] = "ta_isr_touch_t"
    c_union_arm: ClassVar[str] = "isr_touch"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_u16("x"), _u16("y"))


@dataclass
class IsrRotary(TaskEvent):
    steps: int
    vel_q8: int

    type_id: ClassVar[int] = C.TA_EV_ISR_ROTARY
    type_name: ClassVar[str] = "IsrRotary"
    c_type_name: ClassVar[str] = "ta_isr_rotary_t"
    c_union_arm: ClassVar[str] = "isr_rotary"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_i8("steps"), _u8("vel_q8"))


@dataclass
class NetPollPlayerstate(TaskEvent):
    reply_to: str

    type_id: ClassVar[int] = C.TA_EV_NET_POLL
    type_name: ClassVar[str] = "NetPollPlayerstate"
    c_type_name: ClassVar[str] = "ta_net_poll_playerstate_t"
    c_union_arm: ClassVar[str] = "net_poll_playerstate"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_char("reply_to", C.TA_NAME_MAX),)


@dataclass
class NetSet(TaskEvent):
    reply_to: str
    op: int
    volume: int

    type_id: ClassVar[int] = C.TA_EV_NET_SET
    type_name: ClassVar[str] = "NetSet"
    c_type_name: ClassVar[str] = "ta_net_set_t"
    c_union_arm: ClassVar[str] = "net_set"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _char("reply_to", C.TA_NAME_MAX),
        _u8("op"),
        _u8("volume"),
    )


@dataclass
class NetFetchAlbumart(TaskEvent):
    reply_to: str
    path: str

    type_id: ClassVar[int] = C.TA_EV_NET_ALBUMART
    type_name: ClassVar[str] = "NetFetchAlbumart"
    c_type_name: ClassVar[str] = "ta_net_fetch_albumart_t"
    c_union_arm: ClassVar[str] = "net_fetch_albumart"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _char("reply_to", C.TA_NAME_MAX),
        _char("path", C.TA_PATH_MAX),
    )


@dataclass
class NetHttpReply(TaskEvent):
    http_status: int
    n: int
    payload: bytes

    type_id: ClassVar[int] = C.TA_EV_NET_HTTP_REPLY
    type_name: ClassVar[str] = "NetHttpReply"
    c_type_name: ClassVar[str] = "ta_net_http_reply_t"
    c_union_arm: ClassVar[str] = "net_http_reply"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _u16("http_status"),
        _u16("n"),
        FieldSpec(
            name="payload",
            kind="bytes",
            size=C.TA_NET_HTTP_REPLY_MAX,
            length_field="n",
            flat=False,
            c_name="bytes",
        ),
    )


@dataclass
class CoordInformPlayerstate(TaskEvent):
    artist: str
    album: str
    song: str
    playing: int
    volume: int
    track_total_length_secs: int
    track_current_pos_secs: int

    type_id: ClassVar[int] = C.TA_EV_NET_POLL_DONE
    type_name: ClassVar[str] = "CoordInformPlayerstate"
    c_type_name: ClassVar[str] = "ta_coord_inform_playerstate_t"
    c_union_arm: ClassVar[str] = "coord_inform_playerstate"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _char("artist", C.TA_TEXT_MAX),
        _char("album", C.TA_TEXT_MAX),
        _char("song", C.TA_TEXT_MAX),
        _u8("playing"),
        _u8("volume"),
        _i32("track_total_length_secs"),
        _i32("track_current_pos_secs"),
    )


@dataclass
class DrawInformSonginfo(TaskEvent):
    artist: str
    album: str
    song: str

    type_id: ClassVar[int] = C.TA_EV_DRAW_INFORM_SONGINFO
    type_name: ClassVar[str] = "DrawInformSonginfo"
    c_type_name: ClassVar[str] = "ta_draw_inform_songinfo_t"
    c_union_arm: ClassVar[str] = "draw_inform_songinfo"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _char("artist", C.TA_TEXT_MAX),
        _char("album", C.TA_TEXT_MAX),
        _char("song", C.TA_TEXT_MAX),
    )


@dataclass
class DrawInformVolume(TaskEvent):
    volume: int
    actual: int

    type_id: ClassVar[int] = C.TA_EV_DRAW_INFORM_VOLUME
    type_name: ClassVar[str] = "DrawInformVolume"
    c_type_name: ClassVar[str] = "ta_draw_inform_volume_t"
    c_union_arm: ClassVar[str] = "draw_inform_volume"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_u8("volume"), _i32("actual"))


@dataclass
class DrawInformCurrpos(TaskEvent):
    track_current_pos_secs: int

    type_id: ClassVar[int] = C.TA_EV_DRAW_INFORM_CURRPOS
    type_name: ClassVar[str] = "DrawInformCurrpos"
    c_type_name: ClassVar[str] = "ta_draw_inform_currpos_t"
    c_union_arm: ClassVar[str] = "draw_inform_currpos"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_i32("track_current_pos_secs"),)


@dataclass
class DrawUpdate(TaskEvent):
    reply_to: str
    kind: int
    polled: int
    desired: int
    playing: int
    playing_polled: int

    type_id: ClassVar[int] = C.TA_EV_DRAW_UPDATE
    type_name: ClassVar[str] = "DrawUpdate"
    c_type_name: ClassVar[str] = "ta_draw_update_t"
    c_union_arm: ClassVar[str] = "draw_update"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _char("reply_to", C.TA_NAME_MAX),
        _u8("kind"),
        _u8("polled"),
        _u8("desired"),
        _u8("playing"),
        _u8("playing_polled"),
    )


@dataclass
class DrawPaint(TaskEvent):
    reply_to: str

    type_id: ClassVar[int] = C.TA_EV_DRAW_PAINT
    type_name: ClassVar[str] = "DrawPaint"
    c_type_name: ClassVar[str] = "ta_draw_paint_t"
    c_union_arm: ClassVar[str] = "draw_paint"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_char("reply_to", C.TA_NAME_MAX),)


@dataclass
class DrawReactTouch(TaskEvent):
    x: int
    y: int

    type_id: ClassVar[int] = C.TA_EV_DRAW_REACT_TOUCH
    type_name: ClassVar[str] = "DrawReactTouch"
    c_type_name: ClassVar[str] = "ta_draw_react_touch_t"
    c_union_arm: ClassVar[str] = "draw_react_touch"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_u16("x"), _u16("y"))


@dataclass
class DrawReactRotate(TaskEvent):
    steps: int

    type_id: ClassVar[int] = C.TA_EV_DRAW_REACT_ROTATE
    type_name: ClassVar[str] = "DrawReactRotate"
    c_type_name: ClassVar[str] = "ta_draw_react_rotate_t"
    c_union_arm: ClassVar[str] = "draw_react_rotate"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_i8("steps"),)


@dataclass
class DrawScrollOx(TaskEvent):
    ox: int
    has_ox: int

    type_id: ClassVar[int] = C.TA_EV_DRAW_SCROLL_OX
    type_name: ClassVar[str] = "DrawScrollOx"
    c_type_name: ClassVar[str] = "ta_draw_scroll_ox_t"
    c_union_arm: ClassVar[str] = "draw_scroll_ox"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_i16("ox"), _u8("has_ox"))


@dataclass
class DrawSetText(TaskEvent):
    field: int
    flags: int
    n: int
    ascii: str

    type_id: ClassVar[int] = C.TA_EV_DRAW_SET_TEXT
    type_name: ClassVar[str] = "DrawSetText"
    c_type_name: ClassVar[str] = "ta_draw_set_text_t"
    c_union_arm: ClassVar[str] = "draw_set_text"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _u8("field"),
        _u8("flags"),
        _u8("n"),
        _char("ascii", C.TA_DRAW_TEXT_CHUNK_MAX),
    )


@dataclass
class CtrlToggle(TaskEvent):
    reply_to: str

    type_id: ClassVar[int] = C.TA_EV_CTRL_TOGGLE
    type_name: ClassVar[str] = "CtrlToggle"
    c_type_name: ClassVar[str] = "ta_ctrl_toggle_t"
    c_union_arm: ClassVar[str] = "ctrl_toggle"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_char("reply_to", C.TA_NAME_MAX),)


@dataclass
class CtrlSetActive(TaskEvent):
    reply_to: str

    type_id: ClassVar[int] = C.TA_EV_CTRL_SET_ACTIVE
    type_name: ClassVar[str] = "CtrlSetActive"
    c_type_name: ClassVar[str] = "ta_ctrl_set_active_t"
    c_union_arm: ClassVar[str] = "ctrl_set_active"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_char("reply_to", C.TA_NAME_MAX),)


@dataclass
class CtrlVolume(TaskEvent):
    reply_to: str
    mode: int
    delta: int
    absolute: int

    type_id: ClassVar[int] = C.TA_EV_CTRL_VOLUME
    type_name: ClassVar[str] = "CtrlVolume"
    c_type_name: ClassVar[str] = "ta_ctrl_volume_t"
    c_union_arm: ClassVar[str] = "ctrl_volume"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _char("reply_to", C.TA_NAME_MAX),
        _u8("mode"),
        _i8("delta"),
        _u8("absolute"),
    )


@dataclass
class SchedStart(TaskEvent):
    fire_to: str
    fire_type: int
    period_ms: int
    flags: int

    type_id: ClassVar[int] = C.TA_EV_SCHED_START
    type_name: ClassVar[str] = "SchedStart"
    c_type_name: ClassVar[str] = "ta_sched_start_t"
    c_union_arm: ClassVar[str] = "sched_start"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _char("fire_to", C.TA_NAME_MAX),
        _u16("fire_type"),
        _u32("period_ms"),
        _u8("flags"),
    )


@dataclass
class SchedTick(TaskEvent):
    advance_ms: int

    type_id: ClassVar[int] = C.TA_EV_SCHED_TICK
    type_name: ClassVar[str] = "SchedTick"
    c_type_name: ClassVar[str] = "ta_sched_tick_t"
    c_union_arm: ClassVar[str] = "sched_tick"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (_u32("advance_ms"),)


@dataclass
class DrawSetShapeStack(TaskEvent):
    type_id: ClassVar[int] = C.TA_EV_DRAW_SET_SHAPE_STACK
    type_name: ClassVar[str] = "DrawSetShapeStack"
    c_type_name: ClassVar[str] = "uint8_t"
    c_union_arm: ClassVar[str] = ""
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()


@dataclass
class DrawLog(TaskEvent):
    type_id: ClassVar[int] = C.TA_EV_DRAW_LOG
    type_name: ClassVar[str] = "DrawLog"
    c_type_name: ClassVar[str] = "uint8_t"
    c_union_arm: ClassVar[str] = ""
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()


@dataclass
class NetSetDialect(TaskEvent):
    type_id: ClassVar[int] = C.TA_EV_NET_SET_DIALECT
    type_name: ClassVar[str] = "NetSetDialect"
    c_type_name: ClassVar[str] = "uint8_t"
    c_union_arm: ClassVar[str] = ""
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()


@dataclass
class CtrlNext(TaskEvent):
    type_id: ClassVar[int] = C.TA_EV_CTRL_NEXT
    type_name: ClassVar[str] = "CtrlNext"
    c_type_name: ClassVar[str] = "uint8_t"
    c_union_arm: ClassVar[str] = ""
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()


@dataclass
class CtrlPrev(TaskEvent):
    type_id: ClassVar[int] = C.TA_EV_CTRL_PREV
    type_name: ClassVar[str] = "CtrlPrev"
    c_type_name: ClassVar[str] = "uint8_t"
    c_union_arm: ClassVar[str] = ""
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()


@dataclass
class CtrlPoll(TaskEvent):
    type_id: ClassVar[int] = C.TA_EV_CTRL_POLL
    type_name: ClassVar[str] = "CtrlPoll"
    c_type_name: ClassVar[str] = "uint8_t"
    c_union_arm: ClassVar[str] = ""
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()


@dataclass
class SchedStop(TaskEvent):
    type_id: ClassVar[int] = C.TA_EV_SCHED_STOP
    type_name: ClassVar[str] = "SchedStop"
    c_type_name: ClassVar[str] = "uint8_t"
    c_union_arm: ClassVar[str] = ""
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = ()


@dataclass
class TestRun(TaskEvent):
    mode: int
    selector: str
    reply_to: str

    type_id: ClassVar[int] = C.TA_EV_TEST_RUN
    type_name: ClassVar[str] = "TestRun"
    c_type_name: ClassVar[str] = "ta_test_run_t"
    c_union_arm: ClassVar[str] = "test_run"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _u8("mode"),
        _char("selector", C.TA_TEST_SEL_MAX),
        _char("reply_to", C.TA_NAME_MAX),
    )


@dataclass
class TestDone(TaskEvent):
    status: int
    n_ran: int
    n_fail: int
    elapsed_ms: int
    selector: str

    type_id: ClassVar[int] = C.TA_EV_TEST_DONE
    type_name: ClassVar[str] = "TestDone"
    c_type_name: ClassVar[str] = "ta_test_done_t"
    c_union_arm: ClassVar[str] = "test_done"
    field_specs: ClassVar[Tuple[FieldSpec, ...]] = (
        _u8("status"),
        _u16("n_ran"),
        _u16("n_fail"),
        _u32("elapsed_ms"),
        _char("selector", C.TA_TEST_SEL_MAX),
    )


EVENT_CLASSES: List[Type[TaskEvent]] = [
    Nop,
    LogEmitLine,
    CtrlSetRoute,
    AllPerformInit,
    AllInformResult,
    IsrTouch,
    IsrRotary,
    NetPollPlayerstate,
    NetSet,
    NetFetchAlbumart,
    NetHttpReply,
    CoordInformPlayerstate,
    DrawInformSonginfo,
    DrawInformVolume,
    DrawInformCurrpos,
    DrawUpdate,
    DrawPaint,
    DrawReactTouch,
    DrawReactRotate,
    DrawScrollOx,
    DrawSetText,
    CtrlToggle,
    CtrlSetActive,
    CtrlVolume,
    SchedStart,
    SchedTick,
    DrawSetShapeStack,
    DrawLog,
    NetSetDialect,
    CtrlNext,
    CtrlPrev,
    CtrlPoll,
    SchedStop,
    TestRun,
    TestDone,
]

EVENT_BY_TYPE_ID: Dict[int, Type[TaskEvent]] = {
    cls.type_id: cls for cls in EVENT_CLASSES
}
EVENT_BY_NAME: Dict[str, Type[TaskEvent]] = {
    cls.type_name: cls for cls in EVENT_CLASSES
}
