/* Universal messages: startup init broadcast and async inform result. */
#ifndef SPINME_TA_ALL_H
#define SPINME_TA_ALL_H

/* Post TA_EV_ALL_PERFORM_INIT to every actor registered right now.
 * Returns how many posts succeeded. Does not hold the registry lock
 * across enqueue.
 */
int ta_all_broadcast_perform_init(const char *src);

#endif
