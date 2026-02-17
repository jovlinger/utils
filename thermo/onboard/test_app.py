from unittest import TestCase

# This BEFORE other imports on purpose, so that we are the root before
# others grab pointers to submodules.
import sys
import smbus_fake

sys.modules["smbus"] = smbus_fake

import app
import constants


def equalish(a, b) -> bool:
    if isinstance(a, dict):
        return equalish_dict(a, b)
    if isinstance(a, float):
        return equalish_float(a, b)
    return a == b


def equalish_dict(a: dict, b) -> bool:
    if not isinstance(b, dict):
        return False
    if len(a) != len(b):
        return False
    for k, va in a.items():
        vb = b[k]
        if not equalish(va, vb):
            return False
    return True


epsilon = 0.01


def equalish_float(a: float, b) -> bool:
    return abs(a - b) < epsilon


class AppTest(TestCase):
    # the help message is uniquely stupid to test, but it is a start
    def test_help(self):
        """Test using local call"""
        msg = app.help().get("msg")
        self.assertEqual(constants.help_msg, msg)

    def test_environment(self):
        res = app.environment()
        want = {"humidity_percent": 54.12, "temperature_centigrade": 37.67}
        self.assertTrue(equalish(want, res))
