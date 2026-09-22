# Pedagogy brief: gifted ~12yo coding on a visual REPL

Audience: designers of an imgcomp-backed coding REPL for one gifted
middle-school learner (and a teacher-partner). Lesson topics (draw a
rectangle, animate a sort) are examples; this note is about *how* to teach.

## Learner profile (working assumptions)

- Age ~12, high verbal/abstract capacity, low tolerance for busywork.
- Can hold multi-step plans but still needs *concreteness* when the idea is new.
- Motivation spikes when the thing on screen is *theirs* (a picture, a game
  mechanic, a gadget), not a worksheet exercise.
- Errors are high-emotion events: shame or rage can shut learning down faster
  than difficulty does.

Giftedness here means go deeper and transfer sooner -- not skip the concrete
stage. Skip concreteness and you get brittle symbol manipulation.

## Named methods we borrow

### 1. Constructionism (Papert; Resnick "Four P's")

Learners build personally meaningful *projects*, with *peers* (here: teacher as
co-maker), *passion*, and *play* (tinker, risk, iterate). Coding is a medium
for making, not an end in itself.

Implication for us: the REPL must make "I made that" visible in under a second.
Every successful eval should leave a durable scene the learner can point at.

### 2. Constructivism / agency (Brennan on Scratch teaching)

Agency = define and pursue your own learning goals. Instructivist drills
("type this exact line") fight that. Visual / immediate environments push even
instructivist teachers toward constructivist moves (Kesler et al., 2022).

Implication: prefer prompts like "make the red circle follow the mouse" over
"define a function that takes x and returns ...". Scaffold the *goal*, not the
keystrokes.

### 3. Live coding (teacher models the struggle)

The teacher writes and debugs *in front of* the learner, narrating uncertainty.
The point is the process, not a polished demo.

Implication: the REPL must be comfortable for *two* hands -- learner and
teacher -- with undo, history, and no "wipe the canvas on error" behavior.

### 4. Concreteness fading (Bruner / Fyfe et al. line of work)

Start with the richest concrete representation, then gradually strip toward
abstraction once the idea is stable. For us the fade order is roughly:

1. See a shape on the canvas (pixels / color).
2. Name it and move it (`Translate`, variables).
3. Parameterize (radius, color as values).
4. Generalize (loops, functions, sorting as transform-of-list-of-rects).

Do not start at (4). Gifted kids will *ask* for (4); still land (1)-(3) first
so (4) has referents.

### 5. Debugging as the curriculum (not a side quest)

Experts spend most of their time reading failing states. Novices are taught as
if correct-first is normal. Flip it: bugs are the lesson material.

Implication: hit-testing, pick, and "what color is under the cursor?" are
first-class teaching tools. A warm error that names *what the scene still is*
beats a stack trace that erases the picture.

### 6. Tinkerability (Scratch design values)

Small surface, immediate feedback, low cost of trying a wrong idea. Syntax
should not be the boss fight. (We have not locked learner language yet; whatever
we pick must preserve tinkerability.)

## What "visual bedrock" means here

imgcomp already matches constructionist needs:

| Learner idea | imgcomp handle |
|--------------|----------------|
| Canvas / picture | `NaiveCompositor` viewport + `Surface` |
| Thing I can see | `Shape` (often SDF + `Color`) |
| Put it there | `Translate` / fluent `.translate` |
| Turn / squash | `Rotate` / `Stretch` |
| Layering | scene list, back to front |
| Touch it | `pick` / `dispatch_event` / `on_touch` |
| Save the picture | `render_png` |
| Watch it live | `LivePreview` (Tk host today) |

The REPL's job is to bind *names the learner typed* to those handles and keep
the picture honest after every eval.

## REPL affordances mapped from the methods

| Affordance | Serves | Notes |
|------------|--------|-------|
| Edit-eval-draw under ~100ms for small scenes | Constructionism, tinker | 30fps target is for *animation loops* and drag; single eval can be slower if progress is visible |
| Named bindings visible ("r = red circle") | Agency, concreteness fading | Inspector or side list of live names |
| Errors keep prior scene | Debugging-as-curriculum | Never blank the canvas on exception |
| Warm errors with local coords / hit object | Live coding, debug | "No shape under (12, -4)" beats raw TypeError alone |
| Undo / history of evals | Live coding, play | Teacher and learner share a timeline |
| Pick-to-name (click selects object, inserts name) | Concreteness fading | Bridge from seeing to symbol |
| Frame tick / `on_frame` hook | Animation lessons later | Sorting demos etc. ride this; not day-one |
| Layer / dirty-region cache | 30fps | Implementation concern; pedagogy only needs "motion stays smooth" |

## Teaching moves (teacher-partner checklist)

1. Start every session with something already on the canvas (never a blank fear).
2. Change one knob at a time; narrate the before/after.
3. When stuck, *probe the scene* (pick, sample) before editing more code.
4. Promote learner goals; demote "cover this syntax list."
5. End by exporting a PNG the learner keeps -- project residue matters.

## Deliberately out of scope here

- Full multi-week curriculum.
- Classroom management / multi-student sync.
- Choosing Python-subset vs toy language (still unresolved on the ticket).
- Choosing Tk vs other hosts (Tk is only the current LivePreview implementation).

## Sources (named, not exhaustive)

- Mitchel Resnick, "Give P's a Chance" (Projects, Peers, Passion, Play) --
  Scratch / Lifelong Kindergarten constructionist design.
- Seymour Papert -- constructionism; Logo lineage.
- Karen Brennan -- agency and Scratch teaching (constructivist classroom practice).
- Kesler, Shamir-Inbal, Blau (2022) -- visual programming pushes teaching toward
  constructivist strategies.
- Concreteness-fading literature (Bruner; math-education replications) -- fade
  from concrete representations toward symbols after stability.
- Live-coding pedagogy -- teacher models authentic problem-solving in the tool.

## Next artifacts on this ticket

1. Explicit primitive-to-concept map (table form, imgcomp API accurate).
2. REPL design sketch: eval loop, cache invalidation for ~30fps, minimal API.
3. Spike: LivePreview + dirty/layer cache prototype.
