---
name: win-over-powerpoint
description: >
  On a locked-down machine (Office installed, no admin, no python), convert free
  text -- one section per slide -- from a Word .doc into a PowerPoint deck that
  uses the corporate branding template. Drives the installed PowerPoint through
  the OS-native automation hook (COM via PowerShell on Windows, AppleScript via
  osascript on macOS); installs nothing. Use when the user wants to generate
  branded .pptx slides from a document on a restricted Windows or macOS box.
---

# win-over-powerpoint

Generate a branded PowerPoint deck from a Word document, using only software
that already ships with an Office install. No pip, no admin, no MCP server.

## The idea in one paragraph

Every desktop OS exposes a native automation hook into an installed Office. We
use it to read the source `.doc`, split it into sections (one per slide), open a
deck based on the branded template, and fill in title + bullets + images per
slide. There is no PowerPoint MCP and nothing to install -- the OS automation
layer is the native hook.

## Pick your architecture

The mechanism is OS-specific. Read the file for the machine you are on -- you do
not need the other one.

| OS | Hook | Read |
| --- | --- | --- |
| Windows | PowerShell + Office COM | `windows.md` |
| macOS | AppleScript + `osascript` | `mac.md` |

## Inputs (placeholders -- the user will give real values later)

- **Asset folder** (e.g. `C:\myassets\` or `/Users/me/assets/`): contains
  **exactly one** file named `TEMPLATE.*`. The extension is unknown up front --
  it may be `.potx`, `.pptx`, `.thmx`, `.pot`, or `.ppt`. The platform mechanism
  detects it and branches accordingly.
- **Source doc** (e.g. `C:\mytext.doc`): free text plus the per-slide graphics,
  inline in the document.
- **Output** (e.g. `generated_deck.pptx`): the deck we write.

Path style differs by OS (Windows backslashes vs POSIX forward slashes) -- see
the platform file for the exact quoting/argument rules.

## How the doc is split into slides (the section convention)

This is shared across both architectures. One section == one slide. The scripts
recognise sections like this:

1. **Preferred -- Word heading styles.** A paragraph styled **`Heading 1`**
   starts a new slide and becomes its **title**. Every paragraph after it (until
   the next `Heading 1`) becomes a **body bullet**. Any **inline image** in that
   range is placed on that slide.
2. **Fallback -- literal separators.** If the doc has *no* `Heading 1` styles, a
   line that is exactly `---` separates slides, and the first line of each chunk
   is the title.

Tell the author of the doc which convention they are using. Heading styles are
more robust than `---` markers.

## Verify (both architectures)

Open the resulting `.pptx` and confirm branding applied, one slide per section,
titles/bullets correct, and images landed on the right slides.
