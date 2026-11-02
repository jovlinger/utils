/* Init TaskActor: starts a static entry list (host stub). */
#ifndef SPINME_TA_INIT_H
#define SPINME_TA_INIT_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif


typedef void (*ta_entry_fn)(void);

void ta_init_reset(void);
/* Append name+start; returns -1 if full or bad args. */
int ta_init_add_entry(const char *name, ta_entry_fn start);
/* Call each start() in order (actors register themselves). */
void ta_init_run_entries(void);
size_t ta_init_entry_count(void);


#ifdef __cplusplus
}
#endif
#endif
