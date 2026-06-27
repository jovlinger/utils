#!/bin/sh
# Shared helper for scripts that need a project-local Python venv.

UTILS_VENV_NAMES=".venv venv env"

utils_venv_python_bin() {
	if [ "$#" -ne 1 ]; then
		echo "Usage: utils_venv_python_bin VENV_DIR" >&2
		return 2
	fi

	_venv_dir="$1"
	if [ -x "$_venv_dir/bin/python3" ]; then
		echo "$_venv_dir/bin/python3"
	elif [ -x "$_venv_dir/bin/python" ]; then
		echo "$_venv_dir/bin/python"
	else
		return 1
	fi
}

utils_venv_is_complete() {
	if [ "$#" -ne 1 ]; then
		echo "Usage: utils_venv_is_complete VENV_DIR" >&2
		return 2
	fi

	_venv_dir="$1"
	[ -f "$_venv_dir/bin/activate" ] && utils_venv_python_bin "$_venv_dir" >/dev/null 2>&1
}

find_nearest_utils_venv_dir() {
	if [ "$#" -ne 1 ]; then
		echo "Usage: find_nearest_utils_venv_dir START_DIR" >&2
		return 2
	fi

	_d="$(cd "$1" 2>/dev/null && pwd)" || return 1
	while :; do
		for _name in $UTILS_VENV_NAMES; do
			_candidate="$_d/$_name"
			if [ -d "$_candidate" ]; then
				echo "$_candidate"
				return 0
			fi
		done
		_parent="$(dirname "$_d")"
		if [ "$_parent" = "$_d" ]; then
			return 1
		fi
		_d="$_parent"
	done
}

find_nearest_utils_setup_venv() {
	if [ "$#" -ne 1 ]; then
		echo "Usage: find_nearest_utils_setup_venv START_DIR" >&2
		return 2
	fi

	_d="$(cd "$1" 2>/dev/null && pwd)" || return 1
	while :; do
		if [ -f "$_d/setup-venv.sh" ]; then
			echo "$_d/setup-venv.sh"
			return 0
		fi
		if [ -x "$_d/setup-venv" ]; then
			echo "$_d/setup-venv"
			return 0
		fi
		_parent="$(dirname "$_d")"
		if [ "$_parent" = "$_d" ]; then
			return 1
		fi
		_d="$_parent"
	done
}

print_utils_venv_setup_hint() {
	if [ "$#" -ne 2 ]; then
		echo "Usage: print_utils_venv_setup_hint START_DIR UTILS_ROOT" >&2
		return 2
	fi

	_start_dir="$1"
	_utils_root="$2"
	_setup="$(find_nearest_utils_setup_venv "$_start_dir" 2>/dev/null || true)"
	if [ -n "$_setup" ]; then
		echo "Run: $_setup" >&2
		return 0
	fi

	case "$_start_dir" in
	"$_utils_root"/*)
		echo "Run: $_utils_root/create_pipenv.sh ${_start_dir#$_utils_root/}" >&2
		;;
	*)
		echo "Create a .venv, venv, or env directory and install dependencies." >&2
		;;
	esac
}

resolve_utils_venv() {
	if [ "$#" -ne 2 ]; then
		echo "Usage: resolve_utils_venv START_DIR UTILS_ROOT" >&2
		return 2
	fi

	_start_dir="$(cd "$1" 2>/dev/null && pwd)" || {
		echo "No such directory: $1" >&2
		return 1
	}
	_utils_root="$2"
	_candidate="$(find_nearest_utils_venv_dir "$_start_dir" 2>/dev/null || true)"

	if [ -z "$_candidate" ]; then
		echo "No venv marker (.venv, venv, or env) found walking up from $_start_dir." >&2
		print_utils_venv_setup_hint "$_start_dir" "$_utils_root"
		return 1
	fi

	VENV_DIR="$_candidate"
	export VENV_DIR
	if utils_venv_is_complete "$VENV_DIR"; then
		return 0
	fi

	echo "No usable venv at $VENV_DIR." >&2
	echo "The directory marks where this project's venv belongs, but it has no runnable Python yet." >&2
	print_utils_venv_setup_hint "$_start_dir" "$_utils_root"
	return 1
}
