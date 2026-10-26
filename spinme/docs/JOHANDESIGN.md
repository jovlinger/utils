spinme mk 3
===========

This is the high-level design. 

Our ESP32 has two cores. 

# Core A responsibilities

Core A is 100% ui interactions. It will decode screenpress and rotary encoder.  It will paint the screen. In response to
user actions it will post events to the event stream.  Core A will handle whole rotary decode. Even if this means other
parts of the UI are starved. 

# Core B graphics

We maintain 2 framebuffers 240x240xRGBA. curr, next. and a state variable busy-by-core-A.  core A does not see
next, so that always belongs to core B, but curr traded back and forth.

There is also 240bit long dirty bitmap.

Core A has function redraw(), and busy-by-core-A set. 

Core B prepares the framebuffers, where last is the one that is currently displayed, and curr is the one we want to install. 
Depending on hardware, we can push the whole 


# Core B events

Core B is an asynchronous event stream handler. Events are structs - tagged unions. each carries the data it needs. To
process the queue, we pop an event (the queue is a circular list of event structs (the values, not pointers) so this is
just returning a pointer into the ring, or zero for none). If we get an event, we process it with the event handler,
which is one big case that switches based on the union-tag.  Events are the unit of locking. So all mutation or reads
that require uniform reads must do so via events.  No locks. 

The event queue is a circular list of event structs (say 8?). When we push, we inc tail and write into the pointer.  we
need to poll / pop. Since otherwise we might not own the slot while processing. 


examples are:

from front end

- screen press int x,y
- volume int new_val  
- screen on
- screen off

Each of these invoke the interrup of the interruptable sleep in the core loop below. 


from scheduler
- redraw screen

# B Schedulers

Core B has a list of schedulers. For each iteration around the loop, each scheduler item (also tagged union) is
processed in turn by the schedule-handler, which is also a big switch.

example schedulers:

- All: every scheduler has int millisecond clock of last run. and `every int milliseconds`. If lastrun + every >= nowmillis(), then we run. update lastrun optimistically. 
  - most schedulers are permanent. These don't go away.
  - but there is a second short list of one-off schedulers.  This will be front-full, and zero terminated : when one
    inner item has expired, we move the tail event into its space and zero out tail. Each such has a run-per and also
    expire-by. Most often the same, but can be different.
  - each scheduler does exactly one thing: it pushes an event into the event q. Overflow is a thing and will be logged
    ERROR, but most events missable and idempotent.  (HICAP to verify this property)

- render.  same idea: this enqueues an event. This is the naive version: walk tree down. redraw. If invalid, recalculate
  (this applies to time-dependent functions, or imporatantly caches). 
  Then enque the redraw event, attempt 0

- redraw. poll for not busy-by-core-A. if still busy, one-off schedule redraw in +50 ms, and attempt +=1 . log error at 5 attempts
  if done, compare last and curr. Mark dirty linewise into dirty line bitmap. 
  swap curr<->next last pointers, and ping Core A.redraw() 

- clock. enqueue Update vars for logical int seconds and absolutemillis clock.

- player poll. update the state of the variables over the net from MPD (or sonos similar).  
  Can we use event bus to hide latency? (that's v2, at least) 

# B loop

the core loop is: 
  - poll event
     - if not none: handle top element, then pop.
  - run schedulers -> next run delay.
  - interruptable sleep until npw + next run delay

# Graphics

each shape is a tagged union struct. 

In the naive 1st each shape has bounding rect. We walk the tree depth first and draw driectly onto the backing store.
Drawing the shape resets the invalid flag. All shapes can hold a function pointer that takes a pointer to self-shape.
mostly it just return false - not updated.  but it can update things about the same (for example, the shape might hold
the old album name, and if different, we render the new album name, store it, and return true, indicating that parents
need to invalidate any cache they hold that overlaps. The function can also update variables based on global logical and
absolute timers. 
