#!/bin/sh
# Shared helper for scripts that need a project-local Python venv.

resolve_utils_venv() {
	if [ "$#" -ne 2 ]; then
		echo "Usage: resolve_utils_venv PROJECT_DIR UTILS_ROOT" >&2
		return 2
	fi

	_project_dir="$1"
	_utils_root="$2"

	if [ -f "$_project_dir/.venv/bin/activate" ]; then
		VENV_DIR="$_project_dir/.venv"
	elif [ -f "$_project_dir/env/bin/activate" ]; then
		VENV_DIR="$_project_dir/env"
	else
		echo "No venv at $_project_dir/.venv or $_project_dir/env." >&2
		echo "Run: $_utils_root/create_pipenv.sh ${_project_dir#$_utils_root/}" >&2
		return 1
	fi

	export VENV_DIR
	return 0
}
