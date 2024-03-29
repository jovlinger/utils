"""
Standard functions used everywhere, like:
"""
from datetime import datetime
import os

LOG_EVERY=-10
LOG_ERROR=-2
LOG_WARN=-1
LOG_INFO=0
LOG_DEBUG=1
LOG_TRACE=2

LOGLEVEL=LOG_INFO

def log(lvl: int, msg: str, **kwargs):
    print(f"{lvl} <? {LOGLEVEL}")
    if LOGLEVEL < lvl : return
    now = datetime.now().isoformat()
    print(f"{now} - {msg} {kwargs}")

# possibly the least informative name ever
ENVVAR='ENV'

def is_test_env():
    """Are we running in a test environment?"""
    return os.environ.get(ENVVAR) in ['TEST', 'DOCKERTEST']
