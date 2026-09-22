#!/usr/bin/env bash
# Remove mistaken nested album duplicates under files/ (top-level copies already exist).
# Leaves Placebo/VA - Meds and Squirrel Nut Zippers/MEDIA alone.
#
# Usage (from a terminal where sudo works):
#   with-ro-remounted-rw.sh /path/to/utils/shadup/fix-junk-nested-albums.sh
set -euo pipefail

FILES="${SHASRV_FILES:-/mnt/sdb2/music/flac/files}"
LC="$FILES/Leonard Cohen - Songs of Love and Hate"
PIX="$FILES/Pixies - Trompe Le Monde"

if [ ! -d "$FILES" ]; then
  echo "missing files root: $FILES" >&2
  exit 1
fi
if [ "${SHASRV_RW:-}" != "1" ]; then
  echo "refusing: filesystem not marked rw (run under with-ro-remounted-rw.sh)" >&2
  exit 2
fi

rm -rf -- \
  "$LC/Leftfield - Rhythm and Stealth- Stealth Remixes" \
  "$LC/Leonard Cohen - Death of a Ladies' Man" \
  "$LC/Leonard Cohen - I’m Your Man" \
  "$LC/Leonard Cohen - New Skin for the Old Ceremony" \
  "$LC/Massive Attack - Blue Lines" \
  "$LC/Massive Attack - Mezzanine" \
  "$PIX/Popsicle - Lacquer"

echo "removed nested duplicates under Leonard Cohen + Pixies"
echo "left alone:"
ls -1d -- "$FILES/Placebo - Meds/VA - Meds" "$FILES/Squirrel Nut Zippers - Hot/MEDIA"
