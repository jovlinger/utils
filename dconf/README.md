D CONF / Dynamic Configuration
==============================

# Motivating case

The easy way to configure a program is a file. When the program starts up, it reads the file.  To update configs, you
edit the file and restart the program.  For heavier programs(size, deployment, resident state...) this can prove
awkward. And that colors how you use configs

## Motivating case, an aside: What is /configured/?

We have an intiuition. Things like:
  *IP / host names* of outgoing services,
  *Number of connections allowed* for incomming connections.

But not things like
  *Enable test( feature X,
  *Turn on* test feature 00:05-04:00 on apr 4.

This is because configs are slow, and expensive (process wise) to update.

## Motivation, restarted

So the idea here is to provide a *library* that connects to a config store, polling it at some cadence.  The data polled
should in general contain currently active configs (hopefully unchanged) and also future configs, with high-resolution
timestamps for when they should become active.

# Summary

## A data-store

SQL / document / REST access to service.  This is the least important aspect of the application; data volumes will be very low. 

## Configured values.

The type of configuration payload will be JSON.
There is a default value, and that is JSON `null`. That cannot be changed.
If the application needs to distinguish between intentional `null` and there-is-no-value `null`, then the application can just wrap all intentional values in a list or dictionary.



# Semantics

The records in the database are not the same as the records returned by the config *library*, because the library is interpreted.

The unit of interpretation are all entries for a given `key`. 
The result of interpretation is a chronologically sorted list of (possibly different) non-overlapping entries.

## algorithm

* sort entries by insertion time
* active entry for any time is the one with most recent insertion time for the min_t..max_t.  If there are ambiguities, most recent min_t wins.
* max list of time t for distinct min_t, max_t, and ins_t, calculate value at that point, create record from that t to next time.
* coalesce records, emit as results. 


