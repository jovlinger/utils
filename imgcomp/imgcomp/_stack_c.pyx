# cython: language_level=3
"""Cython stack VM engine (cdef op handlers, unboxed data stack).

Authoring body lists use self-evaluating literals (int, float, str) and opcode
name strings. Compile expands literals into internal PC-loaded ``lit_*``
instructions in ``WordBuf`` streams. ``lit_int`` / ``lit_float`` / ``lit_str``
are not surface opcodes.

The data stack and compiled program streams are C arrays; Python objects remain
only in the pre-eval source lists, ``str_pool`` (for ``printf``), and
registration metadata.
"""

from libc.stdint cimport int64_t, uint64_t
from libc.string cimport memcpy

DEF MAX_DATA = 4096
DEF MAX_OPS = 128
DEF MAX_CALL_DEPTH = 256
DEF MAX_BODY_WORDS = 1024


cdef struct WordBuf:
    int hi
    uint64_t elems[MAX_BODY_WORDS]


cdef list op_names = []
cdef int num_ops = 0
cdef op_fn_t handler_table[MAX_OPS]
cdef bint is_body_op[MAX_OPS]
cdef list op_bodies_src = []
cdef WordBuf body_bufs[MAX_OPS]
cdef bint bodies_compiled = False

cdef uint64_t data_stack[MAX_DATA]
cdef int data_sp = 0

cdef list str_pool = []

cdef int call_stack_pc[MAX_CALL_DEPTH]
cdef int call_stack_op[MAX_CALL_DEPTH]
cdef int call_depth = 0
cdef int running_op = -1
cdef int running_pc = 0

cdef bint internal_ops_ready = False
cdef int OP_LIT_INT = -1
cdef int OP_LIT_FLOAT = -1
cdef int OP_LIT_STR = -1


cdef class OpHandler:
    """Opaque token binding a cdef void(void) implementation."""


cdef OpHandler _handler(op_fn_t fn):
    cdef OpHandler token = OpHandler.__new__(OpHandler)
    token.fn = fn
    return token


cdef inline void wordbuf_push(WordBuf* buf, uint64_t word) except *:
    if buf.hi >= MAX_BODY_WORDS:
        raise RuntimeError("body word buffer overflow")
    buf.elems[buf.hi] = word
    buf.hi += 1


cdef inline uint64_t word_from_float(double value) noexcept nogil:
    cdef uint64_t bits
    memcpy(&bits, &value, sizeof(double))
    return bits


cdef inline void data_push_uint(uint64_t value) except *:
    global data_sp
    if data_sp >= MAX_DATA:
        raise RuntimeError("data stack overflow")
    data_stack[data_sp] = value
    data_sp += 1


cdef inline uint64_t data_pop_uint() except *:
    global data_sp
    if data_sp <= 0:
        raise RuntimeError("data stack underflow")
    data_sp -= 1
    return data_stack[data_sp]


cdef inline void data_push_int(int64_t value) except *:
    data_push_uint(<uint64_t>value)


cdef inline int64_t data_pop_int() except *:
    return <int64_t>data_pop_uint()


cdef inline void data_push_float(double value) except *:
    data_push_uint(word_from_float(value))


cdef inline double data_pop_float() except *:
    cdef uint64_t bits = data_pop_uint()
    cdef double value
    memcpy(&value, &bits, sizeof(double))
    return value


cdef inline void data_push_op_id(int op_id) except *:
    data_push_uint(<uint64_t>op_id)


cdef inline int data_pop_op_id() except *:
    cdef int64_t op_id = data_pop_int()
    if op_id < 0 or op_id >= num_ops:
        raise RuntimeError(f"invalid opcode id on stack: {op_id}")
    return <int>op_id


cdef inline void data_push_str_idx(int idx) except *:
    data_push_uint(<uint64_t>idx)


cdef inline int data_pop_str_idx() except *:
    cdef int64_t idx = data_pop_int()
    if idx < 0 or idx >= len(str_pool):
        raise RuntimeError(f"invalid string pool index: {idx}")
    return <int>idx


cdef int intern_str(str value) except *:
    cdef int i
    for i, existing in enumerate(str_pool):
        if existing == value:
            return i
    str_pool.append(value)
    return len(str_pool) - 1


cdef int lookup_op_id(str name) except *:
    cdef int op_id = lookup_opcode_name(name)
    if op_id < 0:
        raise KeyError(f"unknown opcode {name!r}")
    return op_id


cdef int lookup_opcode_name(str name) noexcept:
    """Return opcode id for name, or -1 if not registered."""
    cdef int i
    cdef str existing
    for i, existing in enumerate(op_names):
        if existing == name:
            return i
    return -1


cdef int token_to_op_id(object token) except *:
    cdef int op_id
    if isinstance(token, str):
        return lookup_op_id(token)
    if isinstance(token, int):
        op_id = token
        if op_id < 0 or op_id >= num_ops:
            raise TypeError(f"invalid opcode id in body: {op_id}")
        return op_id
    raise TypeError(f"expected opcode name or id, got {token!r}")


cdef bint _opcode_takes_authoring_operand(int op_id) except *:
    cdef op_fn_t fn = handler_table[op_id]
    return fn == _op_lit_op or fn == _op_if_nzero_run


cdef void _append_authoring_operand(int op_id, WordBuf* buf, object operand) except *:
    if not _opcode_takes_authoring_operand(op_id):
        raise TypeError(f"opcode id {op_id} does not take an authoring operand")
    wordbuf_push(buf, <uint64_t>token_to_op_id(operand))


cdef void compile_body_to_wordbuf(int op_id, WordBuf* buf) except *:
    """Compile authoring list into WordBuf (eval-time, once per reset).

    Surface: ``[3, "hello", "swap", "lit_op", "loop_body"]``
    Compiled: ``[OP_LIT_INT, 3, OP_LIT_STR, idx, OP_SWAP, OP_LIT_OP, OP_LOOP_BODY]``
    """
    cdef list body = <list>op_bodies_src[op_id]
    cdef int i = 0
    cdef int tok_op_id
    cdef object token
    cdef object operand
    cdef str name
    buf.hi = 0
    while i < len(body):
        token = body[i]
        i += 1
        if isinstance(token, int):
            wordbuf_push(buf, <uint64_t>OP_LIT_INT)
            wordbuf_push(buf, <uint64_t><int64_t>token)
            continue
        if isinstance(token, float):
            wordbuf_push(buf, <uint64_t>OP_LIT_FLOAT)
            wordbuf_push(buf, word_from_float(<double>token))
            continue
        if isinstance(token, str):
            name = <str>token
            tok_op_id = lookup_opcode_name(name)
            if tok_op_id < 0:
                wordbuf_push(buf, <uint64_t>OP_LIT_STR)
                wordbuf_push(buf, <uint64_t>intern_str(name))
                continue
            wordbuf_push(buf, <uint64_t>tok_op_id)
            if not _opcode_takes_authoring_operand(tok_op_id):
                continue
            if i >= len(body):
                raise ValueError(f"opcode {name!r} missing operand")
            operand = body[i]
            i += 1
            _append_authoring_operand(tok_op_id, buf, operand)
            continue
        raise TypeError(f"expected int, float, str, or opcode name, got {token!r}")


cdef void compile_all_bodies() except *:
    global bodies_compiled
    cdef int op_id
    if bodies_compiled:
        return
    for op_id in range(num_ops):
        if is_body_op[op_id]:
            compile_body_to_wordbuf(op_id, &body_bufs[op_id])
    bodies_compiled = True


cdef inline WordBuf* running_body() except *:
    return &body_bufs[running_op]


cdef inline uint64_t pc_pop_word() except *:
    global running_pc
    cdef WordBuf* buf = running_body()
    if running_pc >= buf.hi:
        raise IndexError("program counter past end of opcode body")
    cdef uint64_t word = buf.elems[running_pc]
    running_pc += 1
    return word


cdef int64_t pc_pop_int() except *:
    return <int64_t>pc_pop_word()


cdef double pc_pop_float() except *:
    cdef uint64_t bits = pc_pop_word()
    cdef double value
    memcpy(&value, &bits, sizeof(double))
    return value


cdef int pc_pop_str_idx() except *:
    return <int>pc_pop_word()


cdef int pc_pop_op_id() except *:
    cdef int op_id = <int>pc_pop_word()
    if op_id < 0 or op_id >= num_ops:
        raise RuntimeError(f"invalid opcode id in program stream: {op_id}")
    return op_id


cdef void _op_lit_int() except *:
    data_push_int(pc_pop_int())


cdef void _op_lit_float() except *:
    data_push_float(pc_pop_float())


cdef void _op_lit_str() except *:
    data_push_str_idx(pc_pop_str_idx())


cdef void _op_lit_op() except *:
    data_push_op_id(pc_pop_op_id())


cdef void _op_dup() except *:
    cdef uint64_t value = data_stack[data_sp - 1]
    data_push_uint(value)


cdef void _op_drop() except *:
    data_pop_uint()


cdef void _op_swap() except *:
    cdef uint64_t a = data_pop_uint()
    cdef uint64_t b = data_pop_uint()
    data_push_uint(a)
    data_push_uint(b)


cdef void _op_over() except *:
    cdef uint64_t value = data_stack[data_sp - 2]
    data_push_uint(value)


cdef void _op_rot() except *:
    cdef uint64_t a = data_pop_uint()
    cdef uint64_t b = data_pop_uint()
    cdef uint64_t c = data_pop_uint()
    data_push_uint(b)
    data_push_uint(c)
    data_push_uint(a)


cdef void _op_i_add() except *:
    cdef int64_t b = data_pop_int()
    cdef int64_t a = data_pop_int()
    data_push_int(a + b)


cdef void _op_i_sub() except *:
    cdef int64_t b = data_pop_int()
    cdef int64_t a = data_pop_int()
    data_push_int(a - b)


cdef void _op_i_eq() except *:
    cdef int64_t b = data_pop_int()
    cdef int64_t a = data_pop_int()
    data_push_int(1 if a == b else 0)


cdef void _op_i_to_f() except *:
    data_push_float(<double>data_pop_int())


cdef void _op_f_add() except *:
    cdef double b = data_pop_float()
    cdef double a = data_pop_float()
    data_push_float(a + b)


cdef void _op_f_sub() except *:
    cdef double b = data_pop_float()
    cdef double a = data_pop_float()
    data_push_float(a - b)


cdef void _op_f_mul() except *:
    cdef double b = data_pop_float()
    cdef double a = data_pop_float()
    data_push_float(a * b)


cdef void _op_f_gt() except *:
    cdef double b = data_pop_float()
    cdef double a = data_pop_float()
    data_push_int(1 if a > b else 0)


cdef void _op_f_add_at() except *:
    cdef int depth = <int>data_pop_int()
    cdef double delta = data_pop_float()
    cdef int idx
    cdef double acc
    cdef uint64_t bits
    if depth < 0 or depth >= data_sp:
        raise IndexError(f"pick depth out of range: {depth}")
    idx = data_sp - 1 - depth
    bits = data_stack[idx]
    memcpy(&acc, &bits, sizeof(double))
    acc += delta
    memcpy(&bits, &acc, sizeof(double))
    data_stack[idx] = bits


cdef void _op_i_add_at() except *:
    cdef int depth = <int>data_pop_int()
    cdef int64_t delta = data_pop_int()
    cdef int idx
    cdef int64_t acc
    if depth < 0 or depth >= data_sp:
        raise IndexError(f"pick depth out of range: {depth}")
    idx = data_sp - 1 - depth
    acc = <int64_t>data_stack[idx]
    acc += delta
    data_stack[idx] = <uint64_t>acc


cdef void _op_if_nzero_run() except *:
    cdef int64_t cond = data_pop_int()
    cdef int op_id = pc_pop_op_id()
    if cond != 0:
        eval_op_id(op_id)


cdef void _op_call_op() except *:
    eval_op_id(data_pop_op_id())


cdef void _op_printf() except *:
    cdef int argc = <int>data_pop_int()
    cdef list args = []
    cdef int arg_i
    cdef str fmt
    for arg_i in range(argc):
        args.append(data_pop_int())
    args.reverse()
    fmt = <str>str_pool[data_pop_str_idx()]
    print(fmt.format(*args))


cdef void _op_int_incr_le() except *:
    cdef int body_id = data_pop_op_id()
    cdef int64_t incr = data_pop_int()
    cdef int64_t imax = data_pop_int()
    cdef int64_t i = data_pop_int()
    while i <= imax:
        data_push_int(i)
        eval_op_id(body_id)
        i += incr


cdef void _op_float_incr_le() except *:
    cdef int body_id = data_pop_op_id()
    cdef double incr = data_pop_float()
    cdef double imax = data_pop_float()
    cdef double i = data_pop_float()
    while i <= imax:
        data_push_float(i)
        eval_op_id(body_id)
        i += incr


cdef int _alloc_handler_op(str name, op_fn_t fn) except *:
    global num_ops
    cdef int op_id = num_ops
    if num_ops >= MAX_OPS:
        raise RuntimeError("opcode table overflow")
    num_ops += 1
    op_names.append(name)
    handler_table[op_id] = fn
    is_body_op[op_id] = False
    op_bodies_src.append(None)
    return op_id


cdef void ensure_internal_ops() except *:
    global internal_ops_ready, OP_LIT_INT, OP_LIT_FLOAT, OP_LIT_STR
    if internal_ops_ready:
        return
    OP_LIT_INT = _alloc_handler_op("__lit_int", _op_lit_int)
    OP_LIT_FLOAT = _alloc_handler_op("__lit_float", _op_lit_float)
    OP_LIT_STR = _alloc_handler_op("__lit_str", _op_lit_str)
    internal_ops_ready = True


# Surface handlers exported for register_op("name", dup).
lit_op = _handler(_op_lit_op)
dup = _handler(_op_dup)
drop = _handler(_op_drop)
swap = _handler(_op_swap)
over = _handler(_op_over)
rot = _handler(_op_rot)
i_add = _handler(_op_i_add)
i_sub = _handler(_op_i_sub)
i_eq = _handler(_op_i_eq)
i_add_at = _handler(_op_i_add_at)
i_to_f = _handler(_op_i_to_f)
f_add = _handler(_op_f_add)
f_sub = _handler(_op_f_sub)
f_mul = _handler(_op_f_mul)
f_gt = _handler(_op_f_gt)
f_add_at = _handler(_op_f_add_at)
if_nzero_run = _handler(_op_if_nzero_run)
call_op = _handler(_op_call_op)
printf = _handler(_op_printf)
int_incr_le = _handler(_op_int_incr_le)
float_incr_le = _handler(_op_float_incr_le)


cdef void dispatch_op(int op_id) except *:
    if op_id < 0 or op_id >= num_ops:
        raise RuntimeError(f"unknown opcode id {op_id}")
    if is_body_op[op_id]:
        eval_op_id(op_id)
        return
    handler_table[op_id]()


cdef void eval_op_id(int op_id) except *:
    global call_depth, running_op, running_pc
    if call_depth >= MAX_CALL_DEPTH:
        raise RuntimeError("call stack overflow")
    call_stack_op[call_depth] = running_op
    call_stack_pc[call_depth] = running_pc
    call_depth += 1
    running_op = op_id
    running_pc = 0
    run_current_op()
    call_depth -= 1
    running_op = call_stack_op[call_depth]
    running_pc = call_stack_pc[call_depth]


cdef void run_current_op() except *:
    global running_pc
    cdef WordBuf* buf = running_body()
    cdef int op_id
    while running_pc < buf.hi:
        op_id = <int>buf.elems[running_pc]
        running_pc += 1
        dispatch_op(op_id)


def register_op(str name, handler) -> int:
    """Register a cdef handler or a body opcode (authoring token list)."""
    global num_ops
    cdef int op_id
    ensure_internal_ops()
    if name in op_names:
        raise ValueError(f"opcode already registered: {name!r}")
    if num_ops >= MAX_OPS:
        raise RuntimeError("opcode table overflow")
    op_id = num_ops
    num_ops += 1
    op_names.append(name)
    if isinstance(handler, OpHandler):
        handler_table[op_id] = (<OpHandler>handler).fn
        is_body_op[op_id] = False
        op_bodies_src.append(None)
    elif isinstance(handler, list):
        handler_table[op_id] = NULL
        is_body_op[op_id] = True
        op_bodies_src.append(list(handler))
    else:
        raise TypeError("handler must be OpHandler or list")
    return op_id


def reset_vm() -> None:
    global data_sp, call_depth, running_op, running_pc, num_ops, bodies_compiled
    global internal_ops_ready
    cdef int i
    data_sp = 0
    str_pool[:] = []
    num_ops = 0
    bodies_compiled = False
    internal_ops_ready = False
    op_names[:] = []
    op_bodies_src[:] = []
    for i in range(MAX_OPS):
        body_bufs[i].hi = 0
        is_body_op[i] = False
        handler_table[i] = NULL
    call_depth = 0
    running_op = -1
    running_pc = 0


def invoke_op(str name) -> None:
    dispatch_op(lookup_op_id(name))


def push_int(int64_t value) -> None:
    data_push_int(value)


def push_float(double value) -> None:
    data_push_float(value)


def pop_int() -> int:
    return <int>data_pop_int()


def pop_float() -> float:
    return data_pop_float()


def run_op(str name) -> None:
    global running_op, running_pc
    compile_all_bodies()
    running_op = lookup_op_id(name)
    if not is_body_op[running_op]:
        raise TypeError(f"opcode {name!r} is not a body opcode")
    running_pc = 0
    run_current_op()
