# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False
# cython: cdivision=True
"""Cython stack VM engine (cdef op handlers, unboxed data stack).

Authoring body lists use Python values: int/float/str literals and ``OpHandler``
tokens. Compile expands literals into internal PC-loaded ``lit_*`` instructions.
Each registered ``OpHandler`` carries its ``op_id`` after ``register_op``.

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


cdef struct OpEntry:
    bint is_wordbuf
    op_fn_t fn
    WordBuf buf


cdef list op_names = []
cdef int num_ops = 0
cdef OpEntry op_table[MAX_OPS]
cdef list op_bodies_src = []
cdef bint bodies_compiled = False

cdef uint64_t data_stack[MAX_DATA]
cdef bint data_stack_op_lit[MAX_DATA]
cdef int data_sp = 0

cdef list str_pool = []

cdef int call_stack_pc[MAX_CALL_DEPTH]
cdef int call_stack_op[MAX_CALL_DEPTH]
cdef int call_depth = 0

cdef bint eval_started = False

cdef bint internal_ops_ready = False
cdef int OP_LIT_INT = -1
cdef int OP_LIT_FLOAT = -1
cdef int OP_LIT_STR = -1


cdef class OpHandler:
    """Registered opcode token: cdef impl plus table index and metadata."""

    @property
    def id(self) -> int:
        return self.op_id

    @property
    def takes_argument(self) -> bool:
        return bool(self.takes_operand)

    def __repr__(self) -> str:
        if self.op_id < 0:
            return f"OpHandler({self.name!r}, unregistered)"
        return f"OpHandler({self.name!r}, id={self.op_id})"


cdef OpHandler _handler(op_fn_t fn):
    cdef OpHandler token = OpHandler.__new__(OpHandler)
    token.fn = fn
    token.op_id = -1
    token.name = ""
    token.takes_operand = False
    token.is_body = False
    return token


cdef int _bind_handler_op(OpHandler handler, int op_id, str name) except -1:
    handler.op_id = op_id
    handler.name = name
    handler.takes_operand = (
        handler.fn == _op_lit_op
        or handler.fn == _op_if_nzero_run
    )
    handler.is_body = False


cdef OpHandler _make_body_op(int op_id, str name):
    cdef OpHandler token = OpHandler.__new__(OpHandler)
    token.fn = NULL
    token.op_id = op_id
    token.name = name
    token.takes_operand = False
    token.is_body = True
    return token


cdef inline int wordbuf_push(WordBuf* buf, uint64_t word) except -1:
    if buf.hi >= MAX_BODY_WORDS:
        raise RuntimeError("body word buffer overflow")
    buf.elems[buf.hi] = word
    buf.hi += 1


cdef inline uint64_t word_from_float(double value) noexcept nogil:
    cdef uint64_t bits
    memcpy(&bits, &value, sizeof(double))
    return bits


cdef inline double word_to_float(uint64_t bits) noexcept nogil:
    cdef double value
    memcpy(&value, &bits, sizeof(double))
    return value


cdef inline int data_push_uint(uint64_t value) except -1:
    global data_sp
    if data_sp >= MAX_DATA:
        raise RuntimeError("data stack overflow")
    data_stack[data_sp] = value
    data_stack_op_lit[data_sp] = False
    data_sp += 1


cdef inline uint64_t data_pop_uint() except? -1:
    global data_sp
    if data_sp <= 0:
        raise RuntimeError("data stack underflow")
    data_sp -= 1
    return data_stack[data_sp]


cdef inline int data_push_int(int64_t value) except -1:
    data_push_uint(<uint64_t>value)


cdef inline int64_t data_pop_int() except? -1:
    return <int64_t>data_pop_uint()


cdef inline int data_push_float(double value) except -1:
    data_push_uint(word_from_float(value))


cdef inline double data_pop_float() except? -1.0:
    return word_to_float(data_pop_uint())


cdef inline int data_push_op_literal(int op_id) except -1:
    data_push_uint(<uint64_t>op_id)
    data_stack_op_lit[data_sp - 1] = True


cdef inline int data_pop_op_id() except -1:
    cdef int64_t op_id = data_pop_int()
    if op_id < 0 or op_id >= num_ops:
        raise RuntimeError(f"invalid opcode id on stack: {op_id}")
    return <int>op_id


cdef inline int data_pop_op_literal() except -1:
    if data_sp <= 0:
        raise RuntimeError("data stack underflow")
    if not data_stack_op_lit[data_sp - 1]:
        raise AssertionError("loop body must be an op literal pushed by lit_op")
    data_stack_op_lit[data_sp - 1] = False
    return data_pop_op_id()


cdef inline int data_push_str_idx(int idx) except -1:
    data_push_uint(<uint64_t>idx)


cdef inline int data_pop_str_idx() except -1:
    cdef int64_t idx = data_pop_int()
    if idx < 0 or idx >= len(str_pool):
        raise RuntimeError(f"invalid string pool index: {idx}")
    return <int>idx


cdef int intern_str(str value) except -1:
    cdef int i
    for i, existing in enumerate(str_pool):
        if existing == value:
            return i
    str_pool.append(value)
    return len(str_pool) - 1


cdef int lookup_op_id(str name) except -1:
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


cdef int compile_body_to_wordbuf(int op_id, WordBuf* buf) except -1:
    """Compile authoring list into WordBuf (eval-time, once per reset).

    Surface: ``[3, "hello", swap, lit_op, loop_body]`` and
    ``[whilefn, body, while_loop]`` (while peephole).
    """
    cdef list body = <list>op_bodies_src[op_id]
    cdef int i = 0
    cdef OpHandler op
    cdef OpHandler operand_op
    cdef object token
    cdef str text
    buf.hi = 0
    while i < len(body):
        token = body[i]
        if (
            i + 2 < len(body)
            and isinstance(token, OpHandler)
            and isinstance(body[i + 1], OpHandler)
            and isinstance(body[i + 2], OpHandler)
            and (<OpHandler>body[i + 2]).fn == _op_while
        ):
            op = <OpHandler>token
            operand_op = <OpHandler>body[i + 1]
            while_op = <OpHandler>body[i + 2]
            if op.op_id < 0 or operand_op.op_id < 0 or while_op.op_id < 0:
                raise ValueError("while loop ops must be registered")
            wordbuf_push(buf, <uint64_t>while_op.op_id)
            wordbuf_push(buf, <uint64_t>op.op_id)
            wordbuf_push(buf, <uint64_t>operand_op.op_id)
            i += 3
            continue
        i += 1
        if isinstance(token, OpHandler):
            op = <OpHandler>token
            if op.op_id < 0:
                raise ValueError(f"opcode {op.name!r} is not registered")
            wordbuf_push(buf, <uint64_t>op.op_id)
            if not op.takes_operand:
                continue
            if i >= len(body):
                raise ValueError(f"opcode {op.name!r} missing operand")
            token = body[i]
            i += 1
            if not isinstance(token, OpHandler):
                raise TypeError(f"expected OpHandler operand for {op.name!r}")
            operand_op = <OpHandler>token
            if operand_op.op_id < 0:
                raise ValueError(f"opcode operand {operand_op.name!r} is not registered")
            wordbuf_push(buf, <uint64_t>operand_op.op_id)
            continue
        if isinstance(token, int):
            wordbuf_push(buf, <uint64_t>OP_LIT_INT)
            wordbuf_push(buf, <uint64_t><int64_t>token)
            continue
        if isinstance(token, float):
            wordbuf_push(buf, <uint64_t>OP_LIT_FLOAT)
            wordbuf_push(buf, word_from_float(<double>token))
            continue
        if isinstance(token, str):
            text = <str>token
            wordbuf_push(buf, <uint64_t>OP_LIT_STR)
            wordbuf_push(buf, <uint64_t>intern_str(text))
            continue
        raise TypeError(f"expected OpHandler, int, float, or str, got {token!r}")


cdef int compile_all_bodies() except -1:
    global bodies_compiled
    cdef int op_id
    if bodies_compiled:
        return 0
    for op_id in range(num_ops):
        if op_table[op_id].is_wordbuf:
            compile_body_to_wordbuf(op_id, &op_table[op_id].buf)
    bodies_compiled = True


cdef inline bint opcode_is_wordbuf(int op_id) noexcept:
    return op_table[op_id].is_wordbuf


cdef inline WordBuf* running_body() except NULL:
    return &op_table[call_stack_op[call_depth]].buf


cdef inline uint64_t pc_pop_word() except? -1:
    cdef WordBuf* buf = running_body()
    cdef int* pc = &call_stack_pc[call_depth]
    if pc[0] >= buf.hi:
        raise IndexError("program counter past end of opcode body")
    cdef uint64_t word = buf.elems[pc[0]]
    pc[0] += 1
    return word


cdef int64_t pc_pop_int() except? -1:
    return <int64_t>pc_pop_word()


cdef double pc_pop_float() except? -1.0:
    return word_to_float(pc_pop_word())


cdef int pc_pop_str_idx() except -1:
    return <int>pc_pop_word()


cdef int pc_pop_op_id() except -1:
    cdef int op_id = <int>pc_pop_word()
    if op_id < 0 or op_id >= num_ops:
        raise RuntimeError(f"invalid opcode id in program stream: {op_id}")
    return op_id


cdef int _op_lit_int() except -1:
    data_push_int(pc_pop_int())


cdef int _op_lit_float() except -1:
    data_push_float(pc_pop_float())


cdef int _op_lit_str() except -1:
    data_push_str_idx(pc_pop_str_idx())


cdef int _op_lit_op() except -1:
    data_push_op_literal(pc_pop_op_id())


cdef int _op_dup() except -1:
    cdef uint64_t value = data_stack[data_sp - 1]
    cdef bint is_lit = data_stack_op_lit[data_sp - 1]
    data_push_uint(value)
    data_stack_op_lit[data_sp - 1] = is_lit


cdef int _op_drop() except -1:
    data_pop_uint()


cdef int _op_swap() except -1:
    global data_sp
    cdef uint64_t a = data_stack[data_sp - 1]
    cdef uint64_t b = data_stack[data_sp - 2]
    cdef bint a_lit = data_stack_op_lit[data_sp - 1]
    cdef bint b_lit = data_stack_op_lit[data_sp - 2]
    data_stack[data_sp - 1] = b
    data_stack[data_sp - 2] = a
    data_stack_op_lit[data_sp - 1] = b_lit
    data_stack_op_lit[data_sp - 2] = a_lit


cdef int _op_over() except -1:
    cdef uint64_t value = data_stack[data_sp - 2]
    cdef bint is_lit = data_stack_op_lit[data_sp - 2]
    data_push_uint(value)
    data_stack_op_lit[data_sp - 1] = is_lit


cdef int _op_rot() except -1:
    global data_sp
    cdef uint64_t a = data_stack[data_sp - 1]
    cdef uint64_t b = data_stack[data_sp - 2]
    cdef uint64_t c = data_stack[data_sp - 3]
    cdef bint a_lit = data_stack_op_lit[data_sp - 1]
    cdef bint b_lit = data_stack_op_lit[data_sp - 2]
    cdef bint c_lit = data_stack_op_lit[data_sp - 3]
    data_sp -= 3
    data_push_uint(b)
    data_stack_op_lit[data_sp - 1] = b_lit
    data_push_uint(c)
    data_stack_op_lit[data_sp - 1] = c_lit
    data_push_uint(a)
    data_stack_op_lit[data_sp - 1] = a_lit


cdef int _op_i_add() except -1:
    cdef int64_t b = data_pop_int()
    cdef int64_t a = data_pop_int()
    data_push_int(a + b)


cdef int _op_i_sub() except -1:
    cdef int64_t b = data_pop_int()
    cdef int64_t a = data_pop_int()
    data_push_int(a - b)


cdef int _op_i_eq() except -1:
    cdef int64_t b = data_pop_int()
    cdef int64_t a = data_pop_int()
    data_push_int(1 if a == b else 0)


cdef int _op_i_gt() except -1:
    cdef int64_t b = data_pop_int()
    cdef int64_t a = data_pop_int()
    data_push_int(1 if a > b else 0)


cdef int _op_i_to_f() except -1:
    data_push_float(<double>data_pop_int())


cdef int _op_f_add() except -1:
    cdef double b = data_pop_float()
    cdef double a = data_pop_float()
    data_push_float(a + b)


cdef int _op_f_sub() except -1:
    cdef double b = data_pop_float()
    cdef double a = data_pop_float()
    data_push_float(a - b)


cdef int _op_f_mul() except -1:
    cdef double b = data_pop_float()
    cdef double a = data_pop_float()
    data_push_float(a * b)


cdef int _op_f_gt() except -1:
    cdef double b = data_pop_float()
    cdef double a = data_pop_float()
    data_push_int(1 if a > b else 0)


cdef int _op_f_add_at() except -1:
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


cdef int _op_i_add_at() except -1:
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


cdef int _op_if_nzero_run() except -1:
    cdef int64_t cond = data_pop_int()
    cdef int op_id = pc_pop_op_id()
    if cond != 0:
        eval_op_id(op_id)


cdef int _op_call_op() except -1:
    eval_op_id(data_pop_op_id())


cdef int _op_printf() except -1:
    cdef int argc = <int>data_pop_int()
    cdef list args = []
    cdef int arg_i
    cdef str fmt
    for arg_i in range(argc):
        args.append(data_pop_int())
    args.reverse()
    fmt = <str>str_pool[data_pop_str_idx()]
    print(fmt.format(*args))


cdef int _op_int_incr_le() except -1:
    cdef int body_id = data_pop_op_literal()
    cdef int64_t incr = data_pop_int()
    cdef int64_t imax = data_pop_int()
    cdef int64_t i = data_pop_int()
    while i <= imax:
        data_push_int(i)
        run_quoted_body(body_id)
        i += incr


cdef int run_while_loop(int whilefn_id, int body_id) except -1:
    while True:
        run_quoted_body(whilefn_id)
        if data_pop_int() == 0:
            break
        run_quoted_body(body_id)


cdef int _op_while() except -1:
    run_while_loop(pc_pop_op_id(), pc_pop_op_id())


cdef inline int run_wordbuf(WordBuf* buf) except -1:
    """Run a compiled WordBuf with a local PC (no call-frame push)."""
    cdef int bpc = 0
    cdef int op_id
    while bpc < buf.hi:
        op_id = <int>buf.elems[bpc]
        bpc += 1
        if op_id == OP_LIT_INT:
            data_push_int(<int64_t>buf.elems[bpc])
            bpc += 1
        elif op_id == OP_LIT_FLOAT:
            data_push_float(word_to_float(buf.elems[bpc]))
            bpc += 1
        elif op_id == OP_LIT_STR:
            data_push_str_idx(<int>buf.elems[bpc])
            bpc += 1
        elif op_table[op_id].fn == _op_lit_op:
            data_push_op_literal(<int>buf.elems[bpc])
            bpc += 1
        elif op_table[op_id].fn == _op_while:
            run_while_loop(<int>buf.elems[bpc], <int>buf.elems[bpc + 1])
            bpc += 2
        elif opcode_is_wordbuf(op_id):
            eval_op_id(op_id)
        else:
            op_table[op_id].fn()


cdef inline int run_quoted_body(int body_id) except -1:
    if op_table[body_id].is_wordbuf:
        run_wordbuf(&op_table[body_id].buf)
    else:
        op_table[body_id].fn()


cdef int _op_float_incr_le() except -1:
    cdef int body_id = data_pop_op_literal()
    cdef double incr = data_pop_float()
    cdef double imax = data_pop_float()
    cdef double i = data_pop_float()
    while i <= imax:
        data_push_float(i)
        run_quoted_body(body_id)
        i += incr


cdef int _alloc_handler_op(str name, op_fn_t fn) except -1:
    global num_ops
    cdef int op_id = num_ops
    if num_ops >= MAX_OPS:
        raise RuntimeError("opcode table overflow")
    num_ops += 1
    op_names.append(name)
    op_table[op_id].is_wordbuf = False
    op_table[op_id].fn = fn
    op_table[op_id].buf.hi = 0
    op_bodies_src.append(None)
    return op_id


cdef int ensure_internal_ops() except -1:
    global internal_ops_ready, OP_LIT_INT, OP_LIT_FLOAT, OP_LIT_STR
    if internal_ops_ready:
        return 0
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
i_gt = _handler(_op_i_gt)
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
while_loop = _handler(_op_while)


cdef inline int dispatch_op(int op_id) except -1:
    if op_id < 0 or op_id >= num_ops:
        raise RuntimeError(f"unknown opcode id {op_id}")
    if opcode_is_wordbuf(op_id):
        eval_op_id(op_id)
    else:
        op_table[op_id].fn()


cdef int eval_op_id(int op_id) except -1:
    global call_depth
    if call_depth + 1 >= MAX_CALL_DEPTH:
        raise RuntimeError("call stack overflow")
    call_depth += 1
    call_stack_op[call_depth] = op_id
    call_stack_pc[call_depth] = 0
    run_current_op()
    call_depth -= 1


cdef int run_current_op() except -1:
    cdef WordBuf* buf = running_body()
    cdef int* pc = &call_stack_pc[call_depth]
    cdef int op_id
    while pc[0] < buf.hi:
        op_id = <int>buf.elems[pc[0]]
        pc[0] += 1
        dispatch_op(op_id)


def register_op(str name, handler) -> OpHandler:
    """Register a cdef handler or a body opcode (authoring token list)."""
    global num_ops
    cdef int op_id
    cdef OpHandler op_handler
    if eval_started:
        raise RuntimeError("cannot register ops during evaluation")
    ensure_internal_ops()
    if name in op_names:
        raise ValueError(f"opcode already registered: {name!r}")
    if num_ops >= MAX_OPS:
        raise RuntimeError("opcode table overflow")
    op_id = num_ops
    num_ops += 1
    op_names.append(name)
    if isinstance(handler, OpHandler):
        op_handler = <OpHandler>handler
        op_table[op_id].is_wordbuf = False
        op_table[op_id].fn = op_handler.fn
        op_table[op_id].buf.hi = 0
        op_bodies_src.append(None)
        _bind_handler_op(op_handler, op_id, name)
        return op_handler
    if isinstance(handler, list):
        op_table[op_id].is_wordbuf = True
        op_table[op_id].fn = NULL
        op_table[op_id].buf.hi = 0
        op_bodies_src.append(list(handler))
        return _make_body_op(op_id, name)
    raise TypeError("handler must be OpHandler or list")


def reset_vm() -> None:
    global data_sp, call_depth, num_ops, bodies_compiled
    global internal_ops_ready, eval_started
    cdef int i
    data_sp = 0
    str_pool[:] = []
    num_ops = 0
    bodies_compiled = False
    internal_ops_ready = False
    op_names[:] = []
    op_bodies_src[:] = []
    for i in range(MAX_OPS):
        op_table[i].buf.hi = 0
        op_table[i].is_wordbuf = False
        op_table[i].fn = NULL
    call_depth = 0
    eval_started = False


def invoke_op(str name) -> None:
    dispatch_op(lookup_op_id(name))


def push_int(int64_t value) -> None:
    data_push_int(value)


def push_float(double value) -> None:
    data_push_float(value)


def pop_int() -> int:
    return data_pop_int()


def pop_float() -> float:
    return data_pop_float()


def run_op(str name) -> None:
    global call_depth, eval_started
    cdef int op_id
    compile_all_bodies()
    op_id = lookup_op_id(name)
    if not op_table[op_id].is_wordbuf:
        raise TypeError(f"opcode {name!r} is not a body opcode")
    call_depth = 0
    call_stack_op[0] = op_id
    call_stack_pc[0] = 0
    eval_started = True
    try:
        run_current_op()
    finally:
        eval_started = False
