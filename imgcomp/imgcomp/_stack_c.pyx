# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False
# cython: cdivision=True
"""Cython stack VM engine (cdef op handlers, unboxed data stack).

Authoring body lists use Python values: int/float/str literals and ``OpHandler``
tokens. Compile emits tagged instructions with operands resolved early: fn
pointers for native ops, WordBuf pointers for body ops and while loops, and
superinstructions fusing adjacent literal + primitive pairs.
Each registered ``OpHandler`` carries its ``op_id`` after ``register_op``.

The data stack and compiled program streams are C arrays; Python objects remain
only in the pre-eval source lists, ``str_pool`` (for ``printf``), and
registration metadata.
"""

from libc.stdint cimport int64_t, uint64_t, uintptr_t
from libc.string cimport memcpy

DEF MAX_DATA = 4096
DEF MAX_OPS = 128
DEF MAX_CALL_DEPTH = 256
DEF MAX_BODY_WORDS = 1024

# Compiled instruction tags. Compile resolves every operand it can: native
# ops store their fn pointer, body ops and while loops store WordBuf
# pointers (op_table entries are stable after registration).
DEF TAG_CALL_FN = 0
DEF TAG_LIT_INT = 1
DEF TAG_LIT_FLOAT = 2
DEF TAG_LIT_STR = 3
DEF TAG_LIT_OP = 4
DEF TAG_CALL_WB = 5
DEF TAG_WHILE_BUFS = 6
DEF TAG_WHILE_IDS = 7
DEF TAG_IF_NZERO = 8
# Primitive ops inlined into the dispatch loop (no fn-pointer call).
DEF TAG_DUP = 9
DEF TAG_DROP = 10
DEF TAG_SWAP = 11
DEF TAG_OVER = 12
DEF TAG_ROT = 13
DEF TAG_I_ADD = 14
DEF TAG_I_SUB = 15
DEF TAG_I_GT = 16
DEF TAG_I_EQ = 17
DEF TAG_I_TO_F = 18
DEF TAG_F_ADD = 19
DEF TAG_F_SUB = 20
DEF TAG_F_MUL = 21
DEF TAG_F_GT = 22
DEF TAG_I_ADD_AT = 23
DEF TAG_F_ADD_AT = 24
# Superinstructions fused at compile time (operand word kept from the
# literal instruction they absorb).
DEF TAG_I_ADD_C = 25      # a = pop; push a + c
DEF TAG_I_SUB_C = 26      # a = pop; push a - c
DEF TAG_F_ADD_C = 27      # a = pop; push a + c
DEF TAG_F_MUL_C = 28      # a = pop; push a * c
DEF TAG_I_ADD_AT_D = 29   # delta = pop; int add at depth d
DEF TAG_F_ADD_AT_D = 30   # delta = pop; float add at depth d
DEF TAG_I_GT_C = 31       # a = pop; push a > c
DEF TAG_I_EQ_C = 32       # a = pop; push a == c
DEF TAG_F_GT_C = 33       # a = pop; push a > c
DEF TAG_OVER_I_GT = 34    # replace top with (top > second)
DEF TAG_OVER_F_GT = 35    # replace top with (top > second)
DEF TAG_I_GT_C_REV = 36   # push c > top (top stays)
DEF TAG_F_GT_C_REV = 37   # push c > top (top stays)
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

cdef int call_depth = 0

cdef bint eval_started = False



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


cdef int _inline_tag_for_fn(op_fn_t fn) noexcept:
    """Return the inlined-dispatch tag for a primitive handler, or -1."""
    if fn == _op_dup:
        return TAG_DUP
    if fn == _op_drop:
        return TAG_DROP
    if fn == _op_swap:
        return TAG_SWAP
    if fn == _op_over:
        return TAG_OVER
    if fn == _op_rot:
        return TAG_ROT
    if fn == _op_i_add:
        return TAG_I_ADD
    if fn == _op_i_sub:
        return TAG_I_SUB
    if fn == _op_i_gt:
        return TAG_I_GT
    if fn == _op_i_eq:
        return TAG_I_EQ
    if fn == _op_i_to_f:
        return TAG_I_TO_F
    if fn == _op_f_add:
        return TAG_F_ADD
    if fn == _op_f_sub:
        return TAG_F_SUB
    if fn == _op_f_mul:
        return TAG_F_MUL
    if fn == _op_f_gt:
        return TAG_F_GT
    if fn == _op_i_add_at:
        return TAG_I_ADD_AT
    if fn == _op_f_add_at:
        return TAG_F_ADD_AT
    return -1


cdef int _fused_tag(int prev_tag, int cur_tag) noexcept:
    """Return the superinstruction replacing [prev_tag c, cur_tag], or -1."""
    if prev_tag == TAG_LIT_INT:
        if cur_tag == TAG_I_ADD:
            return TAG_I_ADD_C
        if cur_tag == TAG_I_SUB:
            return TAG_I_SUB_C
        if cur_tag == TAG_I_ADD_AT:
            return TAG_I_ADD_AT_D
        if cur_tag == TAG_F_ADD_AT:
            return TAG_F_ADD_AT_D
        if cur_tag == TAG_I_GT:
            return TAG_I_GT_C
        if cur_tag == TAG_I_EQ:
            return TAG_I_EQ_C
    elif prev_tag == TAG_LIT_FLOAT:
        if cur_tag == TAG_F_ADD:
            return TAG_F_ADD_C
        if cur_tag == TAG_F_MUL:
            return TAG_F_MUL_C
        if cur_tag == TAG_F_GT:
            return TAG_F_GT_C
    elif prev_tag == TAG_OVER:
        if cur_tag == TAG_I_GT:
            return TAG_OVER_I_GT
        if cur_tag == TAG_F_GT:
            return TAG_OVER_F_GT
    return -1


cdef int compile_body_to_wordbuf(int op_id, WordBuf* buf) except -1:
    """Compile authoring list into a tagged WordBuf (eval-time, once per reset).

    Surface: ``[3, "hello", swap, lit_op, loop_body]`` and
    ``[whilefn, body, while_loop]`` (while peephole).

    Every instruction is a tag word plus resolved operand words: native ops
    carry their fn pointer, body ops and while loops carry WordBuf pointers.
    Primitive ops get inline-dispatch tags, and adjacent [literal, primitive]
    pairs (plus [literal, over, cmp] triples) fuse into superinstructions.
    """
    cdef list body = <list>op_bodies_src[op_id]
    cdef int i = 0
    cdef OpHandler op
    cdef OpHandler operand_op
    cdef object token
    cdef str text
    cdef int wf_id
    cdef int b_id
    cdef int t
    cdef int fused
    cdef int prev_tag = -1
    cdef int prev_pos = -1
    cdef int prev2_tag = -1
    cdef int prev2_pos = -1
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
            wf_id = op.op_id
            b_id = operand_op.op_id
            if op_table[wf_id].is_wordbuf and op_table[b_id].is_wordbuf:
                wordbuf_push(buf, TAG_WHILE_BUFS)
                wordbuf_push(buf, <uint64_t><uintptr_t>&op_table[wf_id].buf)
                wordbuf_push(buf, <uint64_t><uintptr_t>&op_table[b_id].buf)
            else:
                wordbuf_push(buf, TAG_WHILE_IDS)
                wordbuf_push(buf, <uint64_t>wf_id)
                wordbuf_push(buf, <uint64_t>b_id)
            prev_tag = -1
            prev2_tag = -1
            i += 3
            continue
        i += 1
        if isinstance(token, OpHandler):
            op = <OpHandler>token
            if op.op_id < 0:
                raise ValueError(f"opcode {op.name!r} is not registered")
            if op.fn == _op_while:
                raise ValueError("while requires a [whilefn, body, while] triplet")
            if op.takes_operand:
                if i >= len(body):
                    raise ValueError(f"opcode {op.name!r} missing operand")
                token = body[i]
                i += 1
                if not isinstance(token, OpHandler):
                    raise TypeError(f"expected OpHandler operand for {op.name!r}")
                operand_op = <OpHandler>token
                if operand_op.op_id < 0:
                    raise ValueError(
                        f"opcode operand {operand_op.name!r} is not registered"
                    )
                if op.fn == _op_lit_op:
                    wordbuf_push(buf, TAG_LIT_OP)
                else:
                    wordbuf_push(buf, TAG_IF_NZERO)
                wordbuf_push(buf, <uint64_t>operand_op.op_id)
                prev_tag = -1
                prev2_tag = -1
                continue
            t = _inline_tag_for_fn(op_table[op.op_id].fn)
            if t >= 0:
                fused = _fused_tag(prev_tag, t)
                if fused == TAG_OVER_I_GT and prev2_tag == TAG_LIT_INT:
                    # [lit c, over, i_gt] -> push (c > top), top stays.
                    buf.elems[prev2_pos] = TAG_I_GT_C_REV
                    buf.hi = prev_pos
                    prev_tag = TAG_I_GT_C_REV
                    prev_pos = prev2_pos
                    prev2_tag = -1
                    continue
                if fused == TAG_OVER_F_GT and prev2_tag == TAG_LIT_FLOAT:
                    buf.elems[prev2_pos] = TAG_F_GT_C_REV
                    buf.hi = prev_pos
                    prev_tag = TAG_F_GT_C_REV
                    prev_pos = prev2_pos
                    prev2_tag = -1
                    continue
                if fused >= 0:
                    buf.elems[prev_pos] = <uint64_t>fused
                    prev_tag = fused
                    prev2_tag = -1
                    continue
                prev2_tag = prev_tag
                prev2_pos = prev_pos
                prev_tag = t
                prev_pos = buf.hi
                wordbuf_push(buf, <uint64_t>t)
                continue
            if op_table[op.op_id].is_wordbuf:
                wordbuf_push(buf, TAG_CALL_WB)
                wordbuf_push(buf, <uint64_t><uintptr_t>&op_table[op.op_id].buf)
            else:
                wordbuf_push(buf, TAG_CALL_FN)
                wordbuf_push(
                    buf, <uint64_t><uintptr_t><void*>op_table[op.op_id].fn
                )
            prev_tag = -1
            prev2_tag = -1
            continue
        if isinstance(token, int):
            prev2_tag = prev_tag
            prev2_pos = prev_pos
            prev_tag = TAG_LIT_INT
            prev_pos = buf.hi
            wordbuf_push(buf, TAG_LIT_INT)
            wordbuf_push(buf, <uint64_t><int64_t>token)
            continue
        if isinstance(token, float):
            prev2_tag = prev_tag
            prev2_pos = prev_pos
            prev_tag = TAG_LIT_FLOAT
            prev_pos = buf.hi
            wordbuf_push(buf, TAG_LIT_FLOAT)
            wordbuf_push(buf, word_from_float(<double>token))
            continue
        if isinstance(token, str):
            text = <str>token
            wordbuf_push(buf, TAG_LIT_STR)
            wordbuf_push(buf, <uint64_t>intern_str(text))
            prev_tag = -1
            prev2_tag = -1
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


cdef int _op_lit_op() except -1:
    # Compile-time marker: lit_op tokens become TAG_LIT_OP instructions.
    raise RuntimeError("lit_op cannot be invoked directly")


cdef int _op_dup() except -1:
    cdef uint64_t value = data_stack[data_sp - 1]
    cdef bint is_lit = data_stack_op_lit[data_sp - 1]
    data_push_uint(value)
    data_stack_op_lit[data_sp - 1] = is_lit


cdef int _op_drop() except -1:
    data_pop_uint()


cdef int _op_swap() except -1:
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


cdef inline int f_add_at_depth(int depth) except -1:
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


cdef int _op_f_add_at() except -1:
    f_add_at_depth(<int>data_pop_int())


cdef inline int i_add_at_depth(int depth) except -1:
    cdef int64_t delta = data_pop_int()
    cdef int idx
    cdef int64_t acc
    if depth < 0 or depth >= data_sp:
        raise IndexError(f"pick depth out of range: {depth}")
    idx = data_sp - 1 - depth
    acc = <int64_t>data_stack[idx]
    acc += delta
    data_stack[idx] = <uint64_t>acc


cdef int _op_i_add_at() except -1:
    i_add_at_depth(<int>data_pop_int())


cdef int _op_if_nzero_run() except -1:
    # Compile-time marker: if_nzero_run tokens become TAG_IF_NZERO.
    raise RuntimeError("if_nzero_run cannot be invoked directly")


cdef int _op_call_op() except -1:
    run_quoted_body(data_pop_op_id())


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


cdef int run_while_loop_bufs(WordBuf* whilefn, WordBuf* body) except -1:
    while True:
        run_wordbuf(whilefn)
        if data_pop_int() == 0:
            break
        run_wordbuf(body)


cdef int _op_while() except -1:
    # Compile-time marker: while triplets become TAG_WHILE_* instructions.
    raise RuntimeError("while cannot be invoked directly")


cdef int run_wordbuf(WordBuf* buf) except -1:
    """Interpret a tagged compiled WordBuf with a local PC."""
    global call_depth
    cdef int bpc = 0
    cdef uint64_t tag
    call_depth += 1
    if call_depth >= MAX_CALL_DEPTH:
        raise RuntimeError("call stack overflow")
    while bpc < buf.hi:
        tag = buf.elems[bpc]
        if tag == TAG_CALL_FN:
            (<op_fn_t><void*><uintptr_t>buf.elems[bpc + 1])()
            bpc += 2
        elif tag == TAG_LIT_INT:
            data_push_int(<int64_t>buf.elems[bpc + 1])
            bpc += 2
        elif tag == TAG_LIT_FLOAT:
            data_push_float(word_to_float(buf.elems[bpc + 1]))
            bpc += 2
        elif tag == TAG_LIT_STR:
            data_push_str_idx(<int>buf.elems[bpc + 1])
            bpc += 2
        elif tag == TAG_LIT_OP:
            data_push_op_literal(<int>buf.elems[bpc + 1])
            bpc += 2
        elif tag == TAG_CALL_WB:
            run_wordbuf(<WordBuf*><uintptr_t>buf.elems[bpc + 1])
            bpc += 2
        elif tag == TAG_WHILE_BUFS:
            run_while_loop_bufs(
                <WordBuf*><uintptr_t>buf.elems[bpc + 1],
                <WordBuf*><uintptr_t>buf.elems[bpc + 2],
            )
            bpc += 3
        elif tag == TAG_WHILE_IDS:
            run_while_loop(<int>buf.elems[bpc + 1], <int>buf.elems[bpc + 2])
            bpc += 3
        elif tag == TAG_IF_NZERO:
            bpc += 2
            if data_pop_int() != 0:
                run_quoted_body(<int>buf.elems[bpc - 1])
        elif tag == TAG_DUP:
            _op_dup()
            bpc += 1
        elif tag == TAG_DROP:
            _op_drop()
            bpc += 1
        elif tag == TAG_SWAP:
            _op_swap()
            bpc += 1
        elif tag == TAG_OVER:
            _op_over()
            bpc += 1
        elif tag == TAG_ROT:
            _op_rot()
            bpc += 1
        elif tag == TAG_I_ADD:
            _op_i_add()
            bpc += 1
        elif tag == TAG_I_SUB:
            _op_i_sub()
            bpc += 1
        elif tag == TAG_I_GT:
            _op_i_gt()
            bpc += 1
        elif tag == TAG_I_EQ:
            _op_i_eq()
            bpc += 1
        elif tag == TAG_I_TO_F:
            _op_i_to_f()
            bpc += 1
        elif tag == TAG_F_ADD:
            _op_f_add()
            bpc += 1
        elif tag == TAG_F_SUB:
            _op_f_sub()
            bpc += 1
        elif tag == TAG_F_MUL:
            _op_f_mul()
            bpc += 1
        elif tag == TAG_F_GT:
            _op_f_gt()
            bpc += 1
        elif tag == TAG_I_ADD_AT:
            _op_i_add_at()
            bpc += 1
        elif tag == TAG_F_ADD_AT:
            _op_f_add_at()
            bpc += 1
        elif tag == TAG_I_ADD_C:
            data_push_int(data_pop_int() + <int64_t>buf.elems[bpc + 1])
            bpc += 2
        elif tag == TAG_I_SUB_C:
            data_push_int(data_pop_int() - <int64_t>buf.elems[bpc + 1])
            bpc += 2
        elif tag == TAG_F_ADD_C:
            data_push_float(data_pop_float() + word_to_float(buf.elems[bpc + 1]))
            bpc += 2
        elif tag == TAG_F_MUL_C:
            data_push_float(data_pop_float() * word_to_float(buf.elems[bpc + 1]))
            bpc += 2
        elif tag == TAG_I_ADD_AT_D:
            i_add_at_depth(<int>buf.elems[bpc + 1])
            bpc += 2
        elif tag == TAG_F_ADD_AT_D:
            f_add_at_depth(<int>buf.elems[bpc + 1])
            bpc += 2
        elif tag == TAG_I_GT_C:
            data_push_int(
                1 if data_pop_int() > <int64_t>buf.elems[bpc + 1] else 0
            )
            bpc += 2
        elif tag == TAG_I_EQ_C:
            data_push_int(
                1 if data_pop_int() == <int64_t>buf.elems[bpc + 1] else 0
            )
            bpc += 2
        elif tag == TAG_F_GT_C:
            data_push_int(
                1 if data_pop_float() > word_to_float(buf.elems[bpc + 1]) else 0
            )
            bpc += 2
        elif tag == TAG_OVER_I_GT:
            # [over, i_gt]: replace top with (top > second); second stays.
            data_stack[data_sp - 1] = <uint64_t>(
                1
                if <int64_t>data_stack[data_sp - 1]
                > <int64_t>data_stack[data_sp - 2]
                else 0
            )
            data_stack_op_lit[data_sp - 1] = False
            bpc += 1
        elif tag == TAG_OVER_F_GT:
            data_stack[data_sp - 1] = <uint64_t>(
                1
                if word_to_float(data_stack[data_sp - 1])
                > word_to_float(data_stack[data_sp - 2])
                else 0
            )
            data_stack_op_lit[data_sp - 1] = False
            bpc += 1
        elif tag == TAG_I_GT_C_REV:
            data_push_int(
                1
                if <int64_t>buf.elems[bpc + 1]
                > <int64_t>data_stack[data_sp - 1]
                else 0
            )
            bpc += 2
        elif tag == TAG_F_GT_C_REV:
            data_push_int(
                1
                if word_to_float(buf.elems[bpc + 1])
                > word_to_float(data_stack[data_sp - 1])
                else 0
            )
            bpc += 2
        else:
            raise RuntimeError(f"corrupt instruction tag: {tag}")
    call_depth -= 1


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
    run_quoted_body(op_id)


def register_op(str name, handler) -> OpHandler:
    """Register a cdef handler or a body opcode (authoring token list)."""
    global num_ops
    cdef int op_id
    cdef OpHandler op_handler
    if eval_started:
        raise RuntimeError("cannot register ops during evaluation")
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
    global eval_started
    cdef int i
    data_sp = 0
    str_pool[:] = []
    num_ops = 0
    bodies_compiled = False
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
    eval_started = True
    try:
        run_wordbuf(&op_table[op_id].buf)
    finally:
        eval_started = False
