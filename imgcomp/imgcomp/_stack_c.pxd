# cython: language_level=3
"""Cython declarations for the stack VM engine (cimport from extensions)."""

from libc.stdint cimport int64_t

ctypedef int (*op_fn_t)() except -1

cdef class OpHandler:
    cdef op_fn_t fn
    cdef public int op_id
    cdef public str name
    cdef public bint takes_operand
    cdef public bint is_body

cdef OpHandler _handler(op_fn_t fn)

cdef int data_push_int(int64_t value) except -1
cdef int64_t data_pop_int() except? -1
cdef int data_push_float(double value) except -1
cdef double data_pop_float() except? -1.0
