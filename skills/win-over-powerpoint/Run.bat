@echo off
REM ---------------------------------------------------------------------------
REM Run.bat -- edit the three paths below, then double-click this file.
REM %~dp0 is this folder, so the .ps1 files are found next to this .bat.
REM ---------------------------------------------------------------------------

set "ASSETDIR=C:\myassets"
set "DOCPATH=C:\mytext.doc"
set "OUTPATH=C:\myassets\generated_deck.pptx"
REM Leave LAYOUT empty to auto-pick; set it after running Inspect-Template.
set "LAYOUT="

echo(
echo === Step 1: inspecting template + doc (confirms COM automation works) ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Inspect-Template.ps1" -AssetDir "%ASSETDIR%" -DocPath "%DOCPATH%"
if errorlevel 1 (
    echo(
    echo Inspection failed -- see SKILL.md "If COM automation is blocked".
    pause
    exit /b 1
)

echo(
echo === Step 2: building the deck ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Convert-DocToDeck.ps1" -AssetDir "%ASSETDIR%" -DocPath "%DOCPATH%" -OutPath "%OUTPATH%" -LayoutName "%LAYOUT%"

echo(
echo Done. Output: %OUTPATH%
pause
