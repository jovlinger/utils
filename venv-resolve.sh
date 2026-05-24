# shellcheck shell=sh
# Resolve a utils sub-project virtualenv (.venv preferred; legacy env/ fallback).
#
# Usage (source from another script):
#   . /path/to/utils/venv-resolve.sh
#   resolve_utils_venv "$PROJECT_DIR" || exit 1
#   . "$VENV_DIR/bin/activate"
#
# On failure, prints create instructions and returns 1.

resolve_utils_venv() {
	PROJECT_DIR="$1"
	UTILS_ROOT="${2:-}"

	if [ -z "$PROJECT_DIR" ]; then
		echo "venv-resolve: project directory required" >&2
		return 1
	fi

	if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
		VENV_DIR="$PROJECT_DIR/.venv"
		return 0
	fi
	if [ -f "$PROJECT_DIR/env/bin/activate" ]; then
		VENV_DIR="$PROJECT_DIR/env"
		echo "venv-resolve: using legacy env/ at $VENV_DIR (prefer .venv — re-run create_pipenv.sh)" >&2
		return 0
	fi

	if [ -z "$UTILS_ROOT" ]; then
		UTILS_ROOT="$(cd "$(dirname "$0")" && pwd)"
	fi
	PROJECT_REL="${PROJECT_DIR#"$UTILS_ROOT"/}"
	case "$PROJECT_REL" in
	"$PROJECT_DIR")
		PROJECT_REL="$(basename "$PROJECT_DIR")"
		;;
	esac

	echo "No venv at $PROJECT_DIR/.venv (or legacy env/)." >&2
	echo "Run: $UTILS_ROOT/create_pipenv.sh $PROJECT_REL" >&2
	echo "Note: bin/ uses its own shared venv — bin/setup-venv.sh → bin/.venv (not for utils projects)." >&2
	return 1
}
