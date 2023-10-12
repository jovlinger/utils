# utils

These are all mananged as their own virtual env / requirements.txt

## make an env

> cd utils/foo
> python3 -m pip --version 
Should say something nice, else you need to (python3 -m pip install --user --upgrade pip)

> python3 -m pip install --user virtualenv 
This is needed once, and then we should be able to make more envs like so:

> python3 -m venv env
This makes an env for this checkout of `foo`.  If we had several, we would cd into each and make an env in each. 
This makes directory utils/foo/env. This should be git-ignored.

> source env/bin/activate
This turns on our install, for this shell. (deactivate) to leave, or just close the shell.
