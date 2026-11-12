#include "ta_log_rings.h"

#include <stdlib.h>
#include <string.h>

/* Live nodes on a ring are a circular doubly-linked list: head is the
 * oldest line, tail is the newest. Links are byte offsets from the
 * arena base so a later PSRAM map does not have to relocate pointers.
 * TA_LOG_OFF_NULL is the empty sentinel. Offset 0 is a valid node (it
 * is the start of the ERROR region). */

#define TA_LOG_OFF_NULL 0xffffffffu

typedef struct ta_log_node {
    uint32_t prev;
    uint32_t next;
    uint64_t time_ms;
    uint32_t seq;
    uint32_t repeat;
    uint32_t block_size;
    uint16_t text_len;
    uint8_t level;
    uint8_t pad;
} ta_log_node_t;

typedef char ta_log_node_hdr_is_32[(sizeof(ta_log_node_t) == 32u) ? 1 : -1];

/* Overlay written only while a block sits on the per-ring free list. */
typedef struct ta_log_free {
    uint32_t size;
    uint32_t next;
} ta_log_free_t;

typedef struct ta_log_ring {
    uint32_t base;
    uint32_t cap;
    uint32_t head;
    uint32_t tail;
    uint32_t free_head;
    uint32_t bump;
    uint32_t count;
} ta_log_ring_t;

static uint8_t *g_arena;
static int g_ready;
static int g_in_overrun;
static uint32_t g_seq;
static ta_log_ring_t g_rings[TA_LOG_RING_COUNT];

static void *arena_alloc(size_t bytes) {
#ifdef TA_LOG_RINGS_PSRAM
    return ta_log_rings_psram_alloc(bytes);
#else
    return malloc(bytes);
#endif
}

static void arena_free(void *ptr) {
    if (ptr == NULL) {
        return;
    }
#ifdef TA_LOG_RINGS_PSRAM
    ta_log_rings_psram_free(ptr);
#else
    free(ptr);
#endif
}

static ta_log_node_t *node_at(uint32_t off) {
    return (ta_log_node_t *)(void *)(g_arena + off);
}

static char *node_text(ta_log_node_t *node) {
    return (char *)(void *)(node + 1);
}

static ta_log_free_t *free_at(uint32_t off) {
    return (ta_log_free_t *)(void *)(g_arena + off);
}

static ta_log_ring_id_t ring_id_for_level(uint8_t level) {
    if (level == TA_LOG_LEVEL_ERROR) {
        return TA_LOG_RING_ERROR;
    }
    if (level == TA_LOG_LEVEL_WARN) {
        return TA_LOG_RING_WARN;
    }
    return TA_LOG_RING_INFO;
}

static int ring_ok(ta_log_ring_id_t ring) {
    return ring >= TA_LOG_RING_ERROR && ring < TA_LOG_RING_COUNT;
}

uint32_t ta_log_rings_node_bytes(size_t text_len) {
    size_t n;

    if (text_len > TA_LOG_RINGS_TEXT_MAX) {
        return 0;
    }
    n = sizeof(ta_log_node_t) + text_len + 1u;
    n = (n + 7u) & ~(size_t)7u;
    if (n > 0xffffffffu) {
        return 0;
    }
    return (uint32_t)n;
}

static uint32_t next_seq(void) {
    g_seq++;
    if (g_seq == 0u) {
        g_seq = 1u;
    }
    return g_seq;
}

static void ring_clear(ta_log_ring_t *ring, uint32_t base, uint32_t cap) {
    ring->base = base;
    ring->cap = cap;
    ring->head = TA_LOG_OFF_NULL;
    ring->tail = TA_LOG_OFF_NULL;
    ring->free_head = TA_LOG_OFF_NULL;
    ring->bump = 0;
    ring->count = 0;
}

static int align_cap(uint32_t n, uint32_t *out) {
    uint32_t aligned;

    if (n > 0x7fffffffu) {
        return -1;
    }
    aligned = (n + 7u) & ~7u;
    *out = aligned;
    return 0;
}

static void fill_entry(ta_log_ring_id_t ring, const ta_log_node_t *node,
                       ta_log_rings_entry_t *out) {
    out->level = node->level;
    out->ring = (uint8_t)ring;
    out->repeat = node->repeat;
    out->seq = node->seq;
    out->time_ms = node->time_ms;
    out->text = (const char *)(const void *)(node + 1);
}

static void ring_retract_bump(ta_log_ring_t *ring) {
    for (;;) {
        uint32_t prev;
        uint32_t cur;
        int found;

        prev = TA_LOG_OFF_NULL;
        cur = ring->free_head;
        found = 0;
        while (cur != TA_LOG_OFF_NULL) {
            ta_log_free_t *block;
            uint32_t nxt;

            block = free_at(cur);
            if (ring->base + ring->bump == cur + block->size) {
                nxt = block->next;
                if (prev == TA_LOG_OFF_NULL) {
                    ring->free_head = nxt;
                } else {
                    free_at(prev)->next = nxt;
                }
                ring->bump = cur - ring->base;
                found = 1;
                break;
            }
            prev = cur;
            cur = block->next;
        }
        if (!found) {
            break;
        }
    }
}

static void ring_free_block(ta_log_ring_t *ring, uint32_t off, uint32_t size) {
    ta_log_free_t *block;
    uint32_t prev;
    uint32_t cur;

    block = free_at(off);
    block->size = size;
    block->next = TA_LOG_OFF_NULL;
    prev = TA_LOG_OFF_NULL;
    cur = ring->free_head;
    while (cur != TA_LOG_OFF_NULL && cur < off) {
        prev = cur;
        cur = free_at(cur)->next;
    }
    block->next = cur;
    if (prev == TA_LOG_OFF_NULL) {
        ring->free_head = off;
    } else {
        free_at(prev)->next = off;
    }
    if (cur != TA_LOG_OFF_NULL && off + size == cur) {
        block->size = size + free_at(cur)->size;
        block->next = free_at(cur)->next;
        size = block->size;
    }
    if (prev != TA_LOG_OFF_NULL && prev + free_at(prev)->size == off) {
        ta_log_free_t *older;

        older = free_at(prev);
        older->size += size;
        older->next = block->next;
    }
    ring_retract_bump(ring);
}

static uint32_t ring_alloc(ta_log_ring_t *ring, uint32_t need, uint32_t *out_size) {
    uint32_t prev;
    uint32_t cur;

    if (need == 0u || need > ring->cap) {
        return TA_LOG_OFF_NULL;
    }
    prev = TA_LOG_OFF_NULL;
    cur = ring->free_head;
    while (cur != TA_LOG_OFF_NULL) {
        ta_log_free_t *block;
        uint32_t bsize;
        uint32_t bnext;
        uint32_t remain;

        block = free_at(cur);
        bsize = block->size;
        bnext = block->next;
        if (bsize >= need) {
            remain = bsize - need;
            if (remain >= (uint32_t)sizeof(ta_log_free_t)) {
                ta_log_free_t *rest;

                rest = free_at(cur + need);
                rest->size = remain;
                rest->next = bnext;
                if (prev == TA_LOG_OFF_NULL) {
                    ring->free_head = cur + need;
                } else {
                    free_at(prev)->next = cur + need;
                }
                *out_size = need;
            } else {
                if (prev == TA_LOG_OFF_NULL) {
                    ring->free_head = bnext;
                } else {
                    free_at(prev)->next = bnext;
                }
                *out_size = bsize;
            }
            return cur;
        }
        prev = cur;
        cur = bnext;
    }
    if (ring->bump <= ring->cap && need <= ring->cap - ring->bump) {
        uint32_t off;

        off = ring->base + ring->bump;
        ring->bump += need;
        *out_size = need;
        return off;
    }
    return TA_LOG_OFF_NULL;
}

static void link_tail(ta_log_ring_t *ring, uint32_t off) {
    ta_log_node_t *node;

    node = node_at(off);
    if (ring->count == 0u) {
        node->prev = off;
        node->next = off;
        ring->head = off;
        ring->tail = off;
    } else {
        uint32_t tail;
        uint32_t head;

        tail = ring->tail;
        head = ring->head;
        node->prev = tail;
        node->next = head;
        node_at(tail)->next = off;
        node_at(head)->prev = off;
        ring->tail = off;
    }
    ring->count++;
}

static int drop_head(ta_log_ring_t *ring) {
    ta_log_node_t *node;
    uint32_t off;
    uint32_t next;
    uint32_t size;

    if (ring->count == 0u || ring->head == TA_LOG_OFF_NULL) {
        return 0;
    }
    off = ring->head;
    node = node_at(off);
    next = node->next;
    size = node->block_size;
    ring->count--;
    if (ring->count == 0u) {
        ring_clear(ring, ring->base, ring->cap);
        return 1;
    }
    ring->head = next;
    node_at(ring->tail)->next = next;
    node_at(next)->prev = ring->tail;
    ring_free_block(ring, off, size);
    return 1;
}

/* 0 placed, 1 ring is full, -1 the line can never fit in this cap. */
static int place_new(ta_log_ring_t *ring, uint8_t level, uint64_t time_ms,
                     const char *text, size_t len) {
    uint32_t need;
    uint32_t size;
    uint32_t off;
    ta_log_node_t *node;
    char *dst;

    need = ta_log_rings_node_bytes(len);
    size = 0;
    if (need == 0u || need > ring->cap) {
        return -1;
    }
    off = ring_alloc(ring, need, &size);
    if (off == TA_LOG_OFF_NULL) {
        return 1;
    }
    node = node_at(off);
    node->time_ms = time_ms;
    node->seq = next_seq();
    node->repeat = 1u;
    node->block_size = size;
    node->text_len = (uint16_t)len;
    node->level = level;
    node->pad = 0;
    dst = node_text(node);
    memcpy(dst, text, len);
    dst[len] = '\0';
    link_tail(ring, off);
    return 0;
}

int ta_log_rings_set_caps(uint32_t error_bytes, uint32_t warn_bytes,
                          uint32_t info_bytes) {
    uint32_t caps[TA_LOG_RING_COUNT];
    uint32_t total;
    uint32_t base;
    unsigned i;
    uint8_t *arena;
    void *old;

    if (align_cap(error_bytes, &caps[TA_LOG_RING_ERROR]) != 0 ||
        align_cap(warn_bytes, &caps[TA_LOG_RING_WARN]) != 0 ||
        align_cap(info_bytes, &caps[TA_LOG_RING_INFO]) != 0) {
        return -1;
    }
    if (caps[TA_LOG_RING_ERROR] > UINT32_MAX - caps[TA_LOG_RING_WARN]) {
        return -1;
    }
    total = caps[TA_LOG_RING_ERROR] + caps[TA_LOG_RING_WARN];
    if (total > UINT32_MAX - caps[TA_LOG_RING_INFO]) {
        return -1;
    }
    total += caps[TA_LOG_RING_INFO];
    arena = NULL;
    if (total > 0u) {
        arena = (uint8_t *)arena_alloc(total);
        if (arena == NULL) {
            return -1;
        }
    }
    old = g_arena;
    g_arena = arena;
    base = 0;
    for (i = 0; i < (unsigned)TA_LOG_RING_COUNT; i++) {
        ring_clear(&g_rings[i], base, caps[i]);
        base += caps[i];
    }
    g_seq = 0;
    g_in_overrun = 0;
    g_ready = 1;
    arena_free(old);
    return 0;
}

int ta_log_rings_reset(void) {
    return ta_log_rings_set_caps(TA_LOG_RINGS_ERROR_CAP, TA_LOG_RINGS_WARN_CAP,
                                 TA_LOG_RINGS_INFO_CAP);
}

uint32_t ta_log_rings_cap(ta_log_ring_id_t ring) {
    if (!ring_ok(ring) || !g_ready) {
        return 0;
    }
    return g_rings[ring].cap;
}

uint32_t ta_log_rings_count(ta_log_ring_id_t ring) {
    if (!ring_ok(ring) || !g_ready) {
        return 0;
    }
    return g_rings[ring].count;
}

static int ensure_ready(void) {
    if (g_ready) {
        return 0;
    }
    return ta_log_rings_reset();
}

int ta_log_rings_insert(uint8_t level, uint64_t time_ms, const char *text) {
    ta_log_ring_t *ring;
    size_t len;
    uint32_t spins;

    if (ensure_ready() != 0) {
        return -1;
    }
    if (text == NULL) {
        return -1;
    }
    len = strlen(text);
    if (len == 0u || len > TA_LOG_RINGS_TEXT_MAX) {
        return -1;
    }
    ring = &g_rings[ring_id_for_level(level)];
    if (ring->count > 0u && ring->tail != TA_LOG_OFF_NULL) {
        ta_log_node_t *tail;

        tail = node_at(ring->tail);
        if (strcmp(node_text(tail), text) == 0) {
            if (tail->repeat != UINT32_MAX) {
                tail->repeat++;
            }
            tail->time_ms = time_ms;
            tail->seq = next_seq();
            return 0;
        }
    }
    spins = ring->count + 1u;
    while (spins-- > 0u) {
        int placed;

        placed = place_new(ring, level, time_ms, text, len);
        if (placed == 0) {
            return 0;
        }
        if (placed < 0) {
            return -1;
        }
        if (!g_in_overrun) {
            g_in_overrun = 1;
            (void)ta_log_rings_insert((uint8_t)TA_LOG_LEVEL_WARN, time_ms,
                                     TA_LOG_RINGS_OVERRUN_TEXT);
            g_in_overrun = 0;
        }
        if (!drop_head(ring)) {
            return -1;
        }
    }
    return -1;
}

int ta_log_rings_at(ta_log_ring_id_t ring, uint32_t index,
                    ta_log_rings_entry_t *out) {
    uint32_t off;
    uint32_t i;

    if (out == NULL || !ring_ok(ring) || !g_ready) {
        return -1;
    }
    if (index >= g_rings[ring].count || g_rings[ring].head == TA_LOG_OFF_NULL) {
        return -1;
    }
    off = g_rings[ring].head;
    for (i = 0; i < index; i++) {
        off = node_at(off)->next;
    }
    fill_entry(ring, node_at(off), out);
    return 0;
}

static int cmp_off(const void *va, const void *vb) {
    uint32_t oa;
    uint32_t ob;
    const ta_log_node_t *na;
    const ta_log_node_t *nb;

    oa = *(const uint32_t *)va;
    ob = *(const uint32_t *)vb;
    na = node_at(oa);
    nb = node_at(ob);
    if (na->time_ms < nb->time_ms) {
        return -1;
    }
    if (na->time_ms > nb->time_ms) {
        return 1;
    }
    if (na->seq < nb->seq) {
        return -1;
    }
    if (na->seq > nb->seq) {
        return 1;
    }
    return 0;
}

int ta_log_rings_iter_begin(ta_log_rings_iter_t *it) {
    uint32_t n;
    uint32_t k;
    unsigned r;

    if (it == NULL) {
        return -1;
    }
    it->offs = NULL;
    it->n = 0;
    it->i = 0;
    if (ensure_ready() != 0) {
        return -1;
    }
    n = 0;
    for (r = 0; r < (unsigned)TA_LOG_RING_COUNT; r++) {
        n += g_rings[r].count;
    }
    if (n == 0u) {
        return 0;
    }
    it->offs = (uint32_t *)malloc((size_t)n * sizeof(uint32_t));
    if (it->offs == NULL) {
        return -1;
    }
    k = 0;
    for (r = 0; r < (unsigned)TA_LOG_RING_COUNT; r++) {
        uint32_t off;
        uint32_t i;

        if (g_rings[r].count == 0u) {
            continue;
        }
        off = g_rings[r].head;
        for (i = 0; i < g_rings[r].count; i++) {
            it->offs[k++] = off;
            off = node_at(off)->next;
        }
    }
    it->n = k;
    qsort(it->offs, (size_t)it->n, sizeof(uint32_t), cmp_off);
    return 0;
}

int ta_log_rings_iter_next(ta_log_rings_iter_t *it, ta_log_rings_entry_t *out) {
    uint32_t off;
    ta_log_ring_id_t ring;
    unsigned r;

    if (it == NULL || out == NULL || it->offs == NULL || it->i >= it->n) {
        return 0;
    }
    off = it->offs[it->i];
    it->i++;
    ring = TA_LOG_RING_INFO;
    for (r = 0; r < (unsigned)TA_LOG_RING_COUNT; r++) {
        uint32_t base;
        uint32_t end;

        base = g_rings[r].base;
        end = base + g_rings[r].cap;
        if (off >= base && off < end) {
            ring = (ta_log_ring_id_t)r;
            break;
        }
    }
    fill_entry(ring, node_at(off), out);
    return 1;
}

void ta_log_rings_iter_end(ta_log_rings_iter_t *it) {
    if (it == NULL) {
        return;
    }
    free(it->offs);
    it->offs = NULL;
    it->n = 0;
    it->i = 0;
}
