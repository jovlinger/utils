# win-over-powerpoint -- Windows mechanism

Architecture: **Windows** (PowerShell + Office COM). This is the original,
unchanged mechanism. If you are on macOS, read `mac.md` instead.

Read `SKILL.md` first for the shared concepts (inputs, the one-section-per-slide
convention). This file only covers the Windows-specific automation.

## The idea in one paragraph

PowerShell ships with Windows. If Office is installed, PowerPoint and Word each
expose a COM automation server (`PowerPoint.Application`, `Word.Application`)
that any non-admin user can drive. We read the source `.doc` with Word COM,
split it into sections (one per slide), open a deck based on the branded
template with PowerPoint COM, and fill in title + bullets + images per slide.
There is no PowerPoint MCP and nothing to install -- COM is the native hook.

Windows paths use backslashes and often contain spaces -- always quote them
(`"C:\my assets\..."`).

## Files in this folder

| File | Purpose |
| --- | --- |
| `SKILL.md` | Shared guide + platform router. |
| `windows.md` | This file: the Windows COM mechanism. |
| `mac.md` | The macOS AppleScript mechanism. |
| `Inspect-Template.ps1` | **Run first.** Confirms COM automation is allowed, prints the template's real layout names + placeholder indices, and summarises the doc (slide/image counts). |
| `Convert-DocToDeck.ps1` | The worker. Reads the doc, builds the branded deck, saves `.pptx`. |
| `Run.bat` | Double-click launcher: runs the inspector, then the converter. Edit the paths at the top. |

## Procedure for the local agent

1. **Probe + discover.** Run the inspector:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File .\Inspect-Template.ps1 -AssetDir C:\myassets -DocPath C:\mytext.doc
   ```
   - If it reports COM automation failed, stop and see the fallback section.
   - Otherwise, note the exact **layout name** you want (e.g. `Title and Content`)
     from the printed list.
2. **Generate.** Either edit the paths + `LAYOUT` in `Run.bat` and double-click
   it, or run the converter directly:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File .\Convert-DocToDeck.ps1 `
       -AssetDir C:\myassets -DocPath C:\mytext.doc `
       -OutPath C:\myassets\generated_deck.pptx -LayoutName "Title and Content"
   ```
3. **Verify.** Open the resulting `.pptx` and confirm branding applied, one slide
   per section, titles/bullets correct, and images landed on the right slides.

## Things the local agent must resolve (known guess-points)

These are deliberately left open because they depend on the real assets:

- **Template extension.** Detected at runtime from `TEMPLATE.*`. If it is a
  `.pptx` that ships sample slides, `Convert-DocToDeck.ps1` deletes existing
  slides but keeps the masters/theme; comment out that loop to keep intro/outro
  slides.
- **Layout name + placeholder indices.** Come from `Inspect-Template.ps1`. The
  converter auto-picks custom layout #2 if you leave `-LayoutName` blank, which
  is a guess -- prefer setting the real name.
- **Image placement.** The converter stacks images down the right half of each
  slide as a sane default. Adjust the `Left/Top/Width` block in
  `Convert-DocToDeck.ps1` if the branded layout has a dedicated picture
  placeholder you would rather target.
- **Bullet depth / formatting.** Currently every body paragraph is one top-level
  bullet. Extend `Read-Sections` if you need indent levels (e.g. map `Heading 2`
  or leading tabs to bullet depth).

## If COM automation is blocked

Some hardened environments disable Office automation via Group Policy (this is
separate from macro trust settings -- macros-off does not always mean COM-off,
but it can). `New-Object -ComObject PowerPoint.Application` throws immediately if
so. Options, in order, all still install-free:

1. **Raw Open XML via .NET (no PowerPoint needed).** A `.pptx` is a ZIP of XML.
   PowerShell can author it with `System.IO.Compression` + `System.Xml`: copy the
   `TEMPLATE` (if it is `.pptx`/`.potx`, it already *is* an Open XML package),
   add slide parts under `/ppt/slides/`, wire up `presentation.xml` and the
   rels. Tedious but uses only .NET that ships with Windows. This is the true
   no-install fallback now that python is assumed unavailable.
2. **VBA macro inside PowerPoint.** If interactive macros are allowed even when
   external automation is not, the same object-model code runs as a `.pptm`
   macro. Manual, not scriptable from outside.
3. Escalate to TSG for an approved authoring path.
