# Two cores: glass and Volumio

The UI core paints and collects input. The worker core talks to Volumio.
They share a player snapshot and an event queue. The UI core never calls
HTTP, DNS, or WiFi. The worker is the only application task that opens a
socket.

The player snapshot is the last good status, artist, title, and volume.
Volumio is the source of truth for volume. A poll writes that volume into
the snapshot every time it succeeds. A failed poll leaves the previous
snapshot in place. Failure is not a status string on the glass.

The UI core also keeps a desired volume: the absolute level the knob is
aiming at. With no outstanding turn, desired equals the polled volume.
Each detent changes desired immediately. Desired and polled volume diverge
for the short time until a later poll reports the level Volumio reached.
The UI core posts one coalesced absolute volume for that desired level.
Toggle is its own event.

The real volume is drawn in the normal ink. While desired differs, the
same line is drawn again in a second color at alpha 0.5, on top of the
real digits. When the polled volume equals desired, only the real volume
is drawn.

While the backlight is on, the UI core posts a poll about once a second.
After the backlight turns off, it posts no polls. The worker resolves
`miniDSP-SHD.local` once and reuses the address until a connect fails.

```mermaid
flowchart LR
  knob[Knob and touch] --> ui[UI core]
  ui --> panel[Panel]
  ui --> queue[Event queue]
  queue --> worker[Worker core]
  worker --> volumio[Volumio]
  worker --> snap[Player snapshot]
  snap --> ui
```

## Volume turn

The real digits stay on the last polled volume. The desired digits are
the overlay. The worker asks Volumio to move. A later poll is what moves
the real digits.

```mermaid
sequenceDiagram
    participant Knob
    participant UI as UI core
    participant Q as Event queue
    participant W as Worker core
    participant V as Volumio

    Knob->>UI: detent
    UI->>UI: set desired volume
    UI->>UI: paint real volume, overlay desired at alpha 0.5
    UI->>Q: absolute desired volume
    Q->>W: absolute desired volume
    W->>V: set volume
    Note over UI,V: real digits stay put until a poll
```

## Poll while the glass is lit

```mermaid
sequenceDiagram
    participant UI as UI core
    participant Q as Event queue
    participant W as Worker core
    participant V as Volumio

    Note over UI: backlight on
    loop about once a second
        UI->>Q: poll
        Q->>W: poll
        W->>V: getState
        alt response
            V-->>W: status, artist, title, volume
            W->>W: store the snapshot, including volume
            W->>UI: snapshot
            UI->>UI: paint real volume from the poll
            opt desired differs
                UI->>UI: overlay desired at alpha 0.5
            end
        else failed
            V-->>W: fail
            W->>W: leave the snapshot
        end
    end
```

## Backlight off

```mermaid
sequenceDiagram
    participant UI as UI core
    participant Q as Event queue
    participant W as Worker core

    UI->>UI: backlight off
    Note over UI: poll posts stop
    UI--xQ: no further poll
    Note over W: idle until the next event
```

Wake is the reverse. A rising backlight posts one poll immediately, then
the one-second loop runs again until the glass goes dark.
