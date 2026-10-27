/* Scripted Core B run with a mock player. No sockets.
 *
 * integ_sequence_run is the timed body: screen_on, pooled volume, poll,
 * transport press, miss, scroll, screen_off. integ_script_run is that
 * sequence plus the ring-overflow checks (those log ERROR).
 * *checks may be NULL. The return value is the failed-check count.
 */
#ifndef INTEG_SCRIPT_H
#define INTEG_SCRIPT_H

int integ_sequence_run(int *checks);
int integ_script_run(int *checks);

#endif /* INTEG_SCRIPT_H */
