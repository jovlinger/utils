This is just a static copy of selected parts of github.com/jovlinger/bin, manually refreshed by ``make -C extdeps all``.

This is the lazy avoidance of git repo trickery or packaging up jovlinger/bin into something that can live in requirements.txt.

Copied artifacts include ``venv-run`` / ``venv-run.py`` (Python shebang interpreter for utils CLIs), ``run-with-stdout-logged.py``, and ``mock_cmd.py``. Put this directory on ``PATH`` so ``#!/usr/bin/env venv-run`` works.

``run-with-stdout-logged.py`` optional supervision: set ``RUN_WITH_STDOUT_RUNFILE`` to a tmpfs path (e.g. ``/tmp/dmz.run``). While the file exists, the wrapped command is restarted after each exit; remove the file to request shutdown (the wrapper also stops a running child when the file disappears). ``RUN_WITH_STDOUT_RESTART_SECS`` defaults to 1.

One caveat is that this stupid scheme only works for "small" bin-aries that have no requirements.txt of their own, or else the referencing code must satisfy those implied requirements manually as well. 
