"""Deprecated import shim; use :mod:`api.argus_travel`."""

import sys

from api import argus_travel as _implementation

sys.modules[__name__] = _implementation
