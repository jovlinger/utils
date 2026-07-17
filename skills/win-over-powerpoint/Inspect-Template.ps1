# Inspect-Template.ps1
#
# PROBE / DISCOVERY helper. Run this FIRST on the target machine, before
# Convert-DocToDeck.ps1. It answers the two things we cannot know in advance:
#
#   1. Is Office COM automation actually allowed on this locked-down box?
#      (If it is blocked by Group Policy, New-Object throws here and we stop.)
#   2. What are the real layout names / placeholder indices inside the single
#      branded TEMPLATE.* file? You feed the layout name you want back into
#      Convert-DocToDeck.ps1 via -LayoutName.
#
# It also prints a quick summary of the source .doc (candidate slide count and
# image count) so you can sanity-check before generating.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\Inspect-Template.ps1 `
#       -AssetDir C:\myassets -DocPath C:\mytext.doc

param(
    [string]$AssetDir = "C:\myassets",
    [string]$DocPath  = "C:\mytext.doc"
)

$ErrorActionPreference = "Stop"

# MsoTriState values (passed to Office COM methods that want msoTrue/msoFalse).
$msoTrue  = -1
$msoFalse = 0

function Find-Template([string]$dir) {
    # The asset folder is guaranteed to hold exactly one file named TEMPLATE.*
    # We do NOT assume the extension (.potx / .pptx / .thmx / .pot / .ppt).
    $hits = @(Get-ChildItem -Path $dir -Filter "TEMPLATE.*" -File)
    if ($hits.Count -eq 0) { throw "No TEMPLATE.* file found in $dir" }
    if ($hits.Count -gt 1) { throw "Expected exactly one TEMPLATE.* in $dir, found $($hits.Count)" }
    return $hits[0].FullName
}

$template = Find-Template $AssetDir
$ext = [System.IO.Path]::GetExtension($template).ToLower()
Write-Host "Template : $template"
Write-Host "Extension: $ext"
Write-Host ""

# --- Can we automate PowerPoint at all on this machine? ---
try {
    $ppt = New-Object -ComObject PowerPoint.Application
} catch {
    Write-Host "FAILED to start PowerPoint COM automation."
    Write-Host "This machine most likely blocks Office automation via Group Policy,"
    Write-Host "or PowerPoint is not installed. See the fallback section in SKILL.md."
    Write-Host ("Detail: " + $_.Exception.Message)
    exit 1
}
try { $ppt.Visible = $msoTrue } catch { }   # some builds forbid toggling Visible

# Open the template so its slide masters / custom layouts load.
#   .potx/.pot -> open Untitled to spawn a fresh deck based on the template
#   .thmx      -> apply the theme to a blank deck
#   .pptx/.ppt -> open the deck itself (read-only here, we are only inspecting)
switch -Regex ($ext) {
    "\.pot[x]?$" { $deck = $ppt.Presentations.Open($template, $msoTrue, $msoTrue, $msoTrue) }
    "\.thmx$"    { $deck = $ppt.Presentations.Add($msoTrue); $deck.ApplyTheme($template) }
    default      { $deck = $ppt.Presentations.Open($template, $msoTrue, $msoFalse, $msoTrue) }
}

Write-Host "=== Designs / slide masters / custom layouts ==="
$di = 1
foreach ($design in $deck.Designs) {
    Write-Host ("Design[{0}] '{1}'" -f $di, $design.Name)
    $li = 1
    foreach ($layout in $design.SlideMaster.CustomLayouts) {
        Write-Host ("  Layout[{0}] '{1}'  (pass this exact name as -LayoutName)" -f $li, $layout.Name)
        $pi = 1
        foreach ($ph in $layout.Shapes.Placeholders) {
            Write-Host ("      Placeholder[{0}] type={1} name='{2}'" -f $pi, $ph.PlaceholderFormat.Type, $ph.Name)
            $pi++
        }
        $li++
    }
    $di++
}
Write-Host ""
Write-Host "Placeholder type cheat sheet: 13=Title 12=CenterTitle 4=Subtitle 2=Body 7=Object/Content"

$deck.Close()
$ppt.Quit()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null

# --- Source doc summary ---
if (Test-Path $DocPath) {
    Write-Host ""
    Write-Host ("=== Source document summary ({0}) ===" -f $DocPath)
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $wdoc = $word.Documents.Open($DocPath, $false, $true)   # ConfirmConversions=false, ReadOnly=true
    $headings = 0
    foreach ($p in $wdoc.Paragraphs) {
        if ([string]$p.Style.NameLocal -like "Heading 1*") { $headings++ }
    }
    Write-Host ("Heading 1 count (candidate slide count): {0}" -f $headings)
    Write-Host ("Inline images in document              : {0}" -f $wdoc.InlineShapes.Count)
    if ($headings -eq 0) {
        Write-Host "No 'Heading 1' styles found -> Convert-DocToDeck.ps1 will fall back to '---' separators."
    }
    $wdoc.Close($false)
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}

[GC]::Collect(); [GC]::WaitForPendingFinalizers()
Write-Host ""
Write-Host "Inspection complete."
