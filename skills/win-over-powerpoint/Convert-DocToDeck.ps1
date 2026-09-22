# Convert-DocToDeck.ps1
#
# Turn free text (one section per slide) from a Word .doc into a PowerPoint
# deck that uses the corporate branding from the single TEMPLATE.* in the
# asset folder. Uses only what ships with Office (Word + PowerPoint COM) --
# no install, no admin rights, no python.
#
# Section convention (how the doc is split into slides):
#   * A paragraph styled 'Heading 1' starts a NEW slide; its text is the title.
#   * Paragraphs after it (until the next Heading 1) become body bullets.
#   * Inline images are attached to whichever slide's range they fall in.
#   * If the doc has NO 'Heading 1' styles, we fall back to splitting on a line
#     that is exactly '---'; the first line of each chunk becomes the title.
#
# Usage (or just edit + double-click Run.bat):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\Convert-DocToDeck.ps1 `
#       -AssetDir C:\myassets -DocPath C:\mytext.doc `
#       -OutPath C:\myassets\generated_deck.pptx -LayoutName "Title and Content"

param(
    [string]$AssetDir   = "C:\myassets",
    [string]$DocPath    = "C:\mytext.doc",
    [string]$OutPath    = "C:\myassets\generated_deck.pptx",
    # Leave blank to auto-pick a content layout. Set it from Inspect-Template.ps1
    # output once you know the real layout name in the branded template.
    [string]$LayoutName = ""
)

$ErrorActionPreference = "Stop"

$msoTrue  = -1
$msoFalse = 0
$ppSaveAsOpenXMLPresentation = 24   # .pptx
$ppLayoutText = 2                   # generic fallback if template has no custom layouts

function Find-Template([string]$dir) {
    $hits = @(Get-ChildItem -Path $dir -Filter "TEMPLATE.*" -File)
    if ($hits.Count -ne 1) { throw "Expected exactly one TEMPLATE.* in $dir, found $($hits.Count)" }
    return $hits[0].FullName
}

# ---------------------------------------------------------------------------
# 1. Read the .doc into ordered sections. Word must stay OPEN afterwards so we
#    can copy its inline images to the clipboard while building slides, so this
#    returns the live Word/Doc handles for the caller to close at the end.
# ---------------------------------------------------------------------------
function Read-Sections([string]$docPath) {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $doc = $word.Documents.Open($docPath, $false, $true)   # ReadOnly

    $sections = New-Object System.Collections.ArrayList
    $current  = $null
    $sawHeading = $false

    function New-Section([string]$title) {
        return [ordered]@{
            Title   = $title
            Bullets = (New-Object System.Collections.ArrayList)
            Images  = (New-Object System.Collections.ArrayList)
        }
    }

    foreach ($p in $doc.Paragraphs) {
        $style = [string]$p.Style.NameLocal
        # Word paragraph marks are CR (13); image anchors show up as BELL (7).
        $text  = ([string]$p.Range.Text).Trim([char]13, [char]7, [char]10, [char]32)
        $imgs  = $p.Range.InlineShapes

        $isHeading = ($style -like "Heading 1*")
        $isSep     = ($text -eq "---")

        if ($isHeading) {
            $sawHeading = $true
            $current = New-Section $text
            [void]$sections.Add($current)
            continue
        }

        # Fallback splitter only matters when the doc has no Heading 1 styles.
        if ((-not $sawHeading) -and $isSep) {
            $current = New-Section ""   # title filled by next line
            [void]$sections.Add($current)
            continue
        }

        if ($current -eq $null) {
            $current = New-Section $text   # leading text before any marker => title slide
            [void]$sections.Add($current)
            continue
        }

        if ($imgs.Count -gt 0) {
            for ($i = 1; $i -le $imgs.Count; $i++) { [void]$current.Images.Add($imgs.Item($i)) }
        }
        if ($text.Length -gt 0) {
            if ([string]$current.Title -eq "") { $current.Title = $text }   # first line after '---'
            else { [void]$current.Bullets.Add($text) }
        }
    }

    return @{ Word = $word; Doc = $doc; Sections = $sections }
}

# ---------------------------------------------------------------------------
# 2. Open a deck based on the branded template.
# ---------------------------------------------------------------------------
$template = Find-Template $AssetDir
$ext = [System.IO.Path]::GetExtension($template).ToLower()

$ppt = New-Object -ComObject PowerPoint.Application   # throws if automation is blocked
$ppt.Visible = $msoTrue

switch -Regex ($ext) {
    "\.pot[x]?$" { $deck = $ppt.Presentations.Open($template, $msoFalse, $msoTrue, $msoTrue) } # Untitled deck from template
    "\.thmx$"    { $deck = $ppt.Presentations.Add($msoTrue); $deck.ApplyTheme($template) }
    default      { $deck = $ppt.Presentations.Open($template, $msoFalse, $msoFalse, $msoTrue) } # .pptx/.ppt as working deck
}

# Start from a clean slide list but keep the template's masters/layouts/theme.
# Comment this out if the template ships intro/outro slides you want to keep.
while ($deck.Slides.Count -gt 0) { $deck.Slides.Item(1).Delete() }

# ---------------------------------------------------------------------------
# 3. Choose the branded content layout.
# ---------------------------------------------------------------------------
$master = $deck.Designs.Item(1).SlideMaster
$layout = $null
if ($LayoutName -ne "") {
    foreach ($l in $master.CustomLayouts) { if ($l.Name -eq $LayoutName) { $layout = $l; break } }
    if ($layout -eq $null) { Write-Host "WARNING: layout '$LayoutName' not found; auto-picking." }
}
if ($layout -eq $null -and $master.CustomLayouts.Count -ge 2) {
    $layout = $master.CustomLayouts.Item(2)   # index 2 is commonly 'Title and Content'
}

# ---------------------------------------------------------------------------
# 4. Build one slide per section.
# ---------------------------------------------------------------------------
$read = Read-Sections $DocPath
$idx = 0
foreach ($sec in $read.Sections) {
    $idx++
    if ($layout -ne $null) { $slide = $deck.Slides.AddSlide($idx, $layout) }
    else                   { $slide = $deck.Slides.Add($idx, $ppLayoutText) }

    if ($slide.Shapes.HasTitle) {
        $slide.Shapes.Title.TextFrame.TextRange.Text = [string]$sec.Title
    }

    # First non-title placeholder that can hold text becomes the body.
    $body = $null
    foreach ($ph in $slide.Shapes.Placeholders) {
        $t = $ph.PlaceholderFormat.Type
        if ($t -eq 13 -or $t -eq 12) { continue }   # skip Title / CenterTitle
        $body = $ph; break
    }
    if ($body -ne $null -and $sec.Bullets.Count -gt 0) {
        $body.TextFrame.TextRange.Text = ($sec.Bullets -join "`r")
    }

    # Images: copy each from Word, paste onto the slide, stack down the right half.
    $slideW = $deck.PageSetup.SlideWidth
    $top = 100.0
    foreach ($shape in $sec.Images) {
        $shape.Range.Copy()
        Start-Sleep -Milliseconds 200     # let the clipboard settle before pasting
        $pasted = $slide.Shapes.Paste()
        $pasted.LockAspectRatio = $msoTrue
        $maxW = $slideW / 2 - 20
        if ($pasted.Width -gt $maxW) { $pasted.Width = $maxW }
        $pasted.Left = $slideW / 2
        $pasted.Top  = $top
        $top += $pasted.Height + 10
    }
}

# ---------------------------------------------------------------------------
# 5. Save + tidy up.
# ---------------------------------------------------------------------------
$deck.SaveAs($OutPath, $ppSaveAsOpenXMLPresentation)
$deck.Close()
$ppt.Quit()

$read.Doc.Close($msoFalse)
$read.Word.Quit()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)       | Out-Null
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($read.Word) | Out-Null
[GC]::Collect(); [GC]::WaitForPendingFinalizers()

Write-Host ("Wrote {0} ({1} slides)." -f $OutPath, $idx)
