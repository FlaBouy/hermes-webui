"""Deprecated import shim; use :mod:`api.argus_bridge`."""

import sys

from api import argus_bridge as _implementation

sys.modules[__name__] = _implementation
