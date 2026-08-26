"""Deprecated import shim; use :mod:`api.argus_world`."""

import sys

from api import argus_world as _implementation

sys.modules[__name__] = _implementation
