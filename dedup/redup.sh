#!/bin/bash

# redup.sh - Reconstruct files directory with actual contents instead of symlinks
# Usage: redup.sh [--unlink] <source_dir> [destination_dir]
#   source_dir: Directory containing data/ and files/ subdirectories
#   destination_dir: Where to create the reconstructed files (default: ./dup)
#   --unlink: after a full successful export, remove exported files/ entries and
#             their data/ blobs. Blobs never referenced by this export stay.

set -euo pipefail

DEST_DIR="./dup"
UNLINK=false
POSITIONALS=()

usage() {
    echo "Usage: $0 [--unlink] <source_dir> [destination_dir]"
    echo "  source_dir: Directory containing data/ and files/ subdirectories"
    echo "  destination_dir: Where to create the reconstructed files (default: ./dup)"
    echo "  --unlink: After export, remove exported files/ entries and their data/"
    echo "            blobs. Data not referenced by any exported entry is kept."
    echo ""
    echo ""
    echo "Multiple files/ links to the same data/ blob become hardlinks in the"
    echo "export tree (shared inode)."
    exit 1
}

error() {
    echo "Error: $1" >&2
    exit 1
}

info() {
    echo "Info: $1"
}

for arg in "$@"; do
    case "$arg" in
        --unlink) UNLINK=true ;;
        -h|--help) usage ;;
        *) POSITIONALS+=("$arg") ;;
    esac
done

if [ ${#POSITIONALS[@]} -lt 1 ] || [ ${#POSITIONALS[@]} -gt 2 ]; then
    usage
fi

SOURCE_DIR="${POSITIONALS[0]}"
if [ ${#POSITIONALS[@]} -eq 2 ]; then
    DEST_DIR="${POSITIONALS[1]}"
fi

if [ ! -d "$SOURCE_DIR" ]; then
    error "Source directory '$SOURCE_DIR' does not exist"
fi

if [ ! -d "$SOURCE_DIR/data" ]; then
    error "Source directory '$SOURCE_DIR' does not contain a 'data' subdirectory"
fi

if [ ! -d "$SOURCE_DIR/files" ]; then
    error "Source directory '$SOURCE_DIR' does not contain a 'files' subdirectory"
fi

if [ ! -d "$DEST_DIR" ]; then
    info "Creating destination directory: $DEST_DIR"
    mkdir -p "$DEST_DIR"
fi

# Paths recorded for --unlink (only after a full successful export).
# BLOB_FIRST_DEST maps data blob path -> first dest file (tab-separated) so
# later exports of the same blob hardlink and share an inode.
EXPORTED_DATA="$(mktemp)"
EXPORTED_LINKS="$(mktemp)"
BLOB_FIRST_DEST="$(mktemp)"
cleanup_temps() {
    rm -f "$EXPORTED_DATA" "$EXPORTED_LINKS" "$BLOB_FIRST_DEST"
}
trap cleanup_temps EXIT

# Resolve a files/ entry to an absolute data/ blob path, or empty if none.
resolve_data_target() {
    local file_path="$1"
    local target_path

    if [ -L "$file_path" ]; then
        target_path=$(readlink "$file_path")
        if [[ "$target_path" != /* ]]; then
            target_path="$(dirname "$file_path")/$target_path"
        fi
        realpath "$target_path" 2>/dev/null || true
    else
        echo ""
    fi
}

# First destination path already written for this data blob, or empty.
first_dest_for_blob() {
    local data_path="$1"
    awk -F'\t' -v d="$data_path" '$1 == d { print $2; exit }' "$BLOB_FIRST_DEST"
}

process_file() {
    local file_path="$1"
    local relative_path="$2"
    local dest_file="$DEST_DIR/$relative_path"
    local dest_dir
    dest_dir=$(dirname "$dest_file")

    if [ ! -d "$dest_dir" ]; then
        mkdir -p "$dest_dir"
    fi

    if [ -L "$file_path" ]; then
        local target_path
        local first_dest
        target_path=$(resolve_data_target "$file_path")

        if [ -n "$target_path" ] && [ -f "$target_path" ]; then
            first_dest=$(first_dest_for_blob "$target_path")
            if [ -n "$first_dest" ]; then
                info "Hardlink: $relative_path -> $first_dest (shared blob)"
                ln -f "$first_dest" "$dest_file"
            else
                info "Copying: $relative_path -> $target_path"
                cp "$target_path" "$dest_file"
                printf '%s\t%s\n' "$target_path" "$dest_file" >> "$BLOB_FIRST_DEST"
            fi
            printf '%s\n' "$target_path" >> "$EXPORTED_DATA"
            printf '%s\n' "$file_path" >> "$EXPORTED_LINKS"
        else
            error "Symlink target does not exist for '$relative_path'"
        fi
    elif [ -f "$file_path" ]; then
        info "Copying: $relative_path"
        cp "$file_path" "$dest_file"
        # Regular files under files/ have no data/ blob; still drop the entry.
        printf '%s\n' "$file_path" >> "$EXPORTED_LINKS"
    else
        error "Unknown file type for '$relative_path'"
    fi
}

info "Reconstructing files from '$SOURCE_DIR' to '$DEST_DIR'"

total_files=$(find "$SOURCE_DIR/files" \( -type f -o -type l \) | wc -l | tr -d ' ')
current_file=0

while IFS= read -r -d '' file_path; do
    current_file=$((current_file + 1))

    relative_path="${file_path#$SOURCE_DIR/files/}"

    if [ "$relative_path" = "" ]; then
        continue
    fi

    echo "[$current_file/$total_files] Processing: $relative_path"
    process_file "$file_path" "$relative_path"

done < <(find "$SOURCE_DIR/files" \( -type f -o -type l \) -print0)

info "Reconstruction complete! $total_files files processed."
info "Output directory: $DEST_DIR"

if $UNLINK; then
    info "Unlinking exported store entries..."
    unlinked_data=0
    unlinked_links=0

    # Drop data blobs that this export copied (unique). Orphan blobs stay.
    if [ -s "$EXPORTED_DATA" ]; then
        while IFS= read -r data_path; do
            [ -n "$data_path" ] || continue
            if [ -f "$data_path" ]; then
                rm -f "$data_path"
                unlinked_data=$((unlinked_data + 1))
                info "Unlinked data: $data_path"
            fi
        done < <(sort -u "$EXPORTED_DATA")
    fi

    # Remove the files/ entries that were exported (avoid dangling symlinks).
    if [ -s "$EXPORTED_LINKS" ]; then
        while IFS= read -r link_path; do
            [ -n "$link_path" ] || continue
            if [ -e "$link_path" ] || [ -L "$link_path" ]; then
                rm -f "$link_path"
                unlinked_links=$((unlinked_links + 1))
            fi
        done < "$EXPORTED_LINKS"
    fi

    info "Unlink complete: $unlinked_data data blob(s), $unlinked_links files/ entr(y/ies)."
fi
