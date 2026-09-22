# win-over-powerpoint -- macOS mechanism

Architecture: **macOS** (AppleScript + PowerPoint scripting). If you are on
Windows, read `windows.md` instead.

Read `SKILL.md` first for the shared concepts (inputs, the one-section-per-slide
convention). This file only covers the macOS-specific automation.

Everything below has been run and verified on this machine (PowerPoint 16.110,
macOS). No install step, no python.

## The idea in one paragraph

AppleScript ships with macOS (`/usr/bin/osascript`). If PowerPoint is installed
it exposes a rich AppleScript dictionary (`Microsoft PowerPoint.sdef`) that any
user can drive -- this is the macOS analogue of Windows COM. We open (or create)
a presentation, add one slide per section, write the title and bullets into each
slide's placeholders, and save straight to a native `.pptx`. Word on macOS is
also scriptable the same way, so the source `.doc` can be read without python.

macOS paths are POSIX (forward slashes). AppleScript file arguments want a
`POSIX file "/abs/path"` value, not a bare string.

## First run: macOS Automation (TCC) approval

The first time `osascript` drives PowerPoint, macOS shows a one-time
**"<Terminal/app> wants to control Microsoft PowerPoint"** prompt (TCC). Until
it is approved the script fails with `error -1728` (object does not exist) or
`-1743` (not authorized). This is expected, not a bug:

- Approve it once (System Settings > Privacy & Security > Automation), or click
  **OK** on the prompt. After that, runs are non-interactive.
- In a headless/agent context the prompt may block; run the first call
  interactively so the human can approve.

## The scripting object model (verified)

- `make new presentation` returns a presentation reference.
- Add a slide with a built-in layout:
  `make new slide at end of pres with properties {layout:slide layout title slide}`.
  Note it is `at end of pres`, **not** `at end of slides of pres` (the latter
  throws "Can't make class slide", `-2710`).
- Built-in layout constants include: `slide layout title slide`,
  `slide layout text slide`, `slide layout title only`, `slide layout blank`,
  `slide layout section header`, `slide layout comparison`,
  `slide layout content with caption`, `slide layout picture with caption`
  (see the sdef enum `EPPSlideLayout` for the full list).
- Placeholders are `shape` elements of the slide. For the text layouts,
  **shape 1 = title, shape 2 = body**. Set text with:
  `set content of text range of text frame of (shape 2 of s) to "..."`.
- Bullets: separate lines with `return` inside the body placeholder -- each line
  becomes one top-level bullet.
- Save as a real `.pptx`:
  `save pres in (POSIX file outPath) as save as Open XML presentation`.
- `close pres saving no` when done.

## Minimal, tested example

Two slides (a title slide and a bulleted content slide), saved as `.pptx`:

```applescript
on run argv
  set outPath to item 1 of argv
  tell application "Microsoft PowerPoint"
    set pres to make new presentation
    -- Slide 1: title + subtitle
    set s1 to make new slide at end of pres with properties {layout:slide layout title slide}
    set content of text range of text frame of (shape 1 of s1) to "My Deck Title"
    set content of text range of text frame of (shape 2 of s1) to "A subtitle"
    -- Slide 2: title + bullets
    set s2 to make new slide at end of pres with properties {layout:slide layout text slide}
    set content of text range of text frame of (shape 1 of s2) to "Section heading"
    set content of text range of text frame of (shape 2 of s2) to "First bullet" & return & "Second bullet" & return & "Third bullet"
    -- Save native .pptx and close
    save pres in (POSIX file outPath) as save as Open XML presentation
    close pres saving no
  end tell
end run
```

Run it:

```
osascript build_deck.applescript "/Users/me/out/generated_deck.pptx"
```

## Using the branded template

The whole point of this skill is a *branded* deck. Two verified ways to carry
the corporate theme, masters, and colours into the output:

1. **Preferred -- open the template as the base.** Open `TEMPLATE.*`
   (`.potx`/`.pptx`/`.thmx`) as the presentation and add slides to it; the theme
   and slide masters travel with the deck automatically:
   ```applescript
   set pres to open (POSIX file "/Users/me/assets/TEMPLATE.potx")
   ```
   If the template ships sample slides, delete them first but keep the masters:
   `delete slide 1 of pres` in a loop over the originals.
2. **Alternative -- apply the template to a fresh deck.** Create the deck, then
   apply the theme/design file:
   ```applescript
   set pres to make new presentation
   apply template pres file name "/Users/me/assets/TEMPLATE.thmx"
   ```

To target the template's *branded* layouts (not the generic built-ins), assign a
slide's `custom layout` from the master:
`set custom layout of s to custom layout N of (slide master of pres)`.

## Things the local agent must resolve (known guess-points)

Mirrors the Windows guess-points; these depend on the real assets:

- **Custom layouts are index-based on macOS.** Unlike Windows COM (pick a layout
  by name), the AppleScript `custom layout` object exposes **no `name`
  property** -- you select it by position (`custom layout N of the master`).
  First enumerate `count of custom layouts of (slide master of pres)` and, if
  needed, open the template once in the PowerPoint UI to map positions to the
  branded layout you want.
- **Placeholder indices.** shape 1 = title, shape 2 = body holds for the built-in
  text layouts; a custom branded layout may differ. Enumerate
  `count of shapes of s` and check `has text frame of (shape i of s)` to find the
  real title/body placeholders before writing.
- **Images.** Add a picture with
  `make new picture at slide with properties {file name:"/abs/img.png", ...}` and
  set `left/top/width/height`; default to stacking them down the right half of
  the slide unless the branded layout has a dedicated picture placeholder.
- **Reading the source doc.** Word for Mac is scriptable too
  (`tell application "Microsoft Word"`), so the `.doc` can be read and split
  into sections without python. Splitting follows the shared convention in
  `SKILL.md` (Heading 1 starts a slide; `---` fallback).

## If AppleScript automation is blocked

If PowerPoint's scripting is disabled or the TCC prompt cannot be approved:

1. **VBA macro inside PowerPoint.** The same object model runs as a `.pptm`
   macro from the built-in editor when external automation is not allowed.
   Manual, not scriptable from outside.
2. **Raw Open XML.** A `.pptx` is a ZIP of XML; the branded `TEMPLATE` (if
   `.pptx`/`.potx`) already is an Open XML package -- copy it and inject slide
   parts. Install-free but tedious.
3. Escalate to TSG for an approved authoring path.
