"""Deprecated import shim for pre-A.R.G.U.S. integrations.

New runtime code must import :mod:`api.argus_route`.  The module-object alias
keeps old tests and persisted integrations patch-compatible during migration.
"""

import sys

from api import argus_route as _implementation

sys.modules[__name__] = _implementation
