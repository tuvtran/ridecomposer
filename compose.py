#!/usr/bin/env python3
"""Thin entry point so `python3 compose.py [ride]` works without installing.

The real code lives in the `ridecomposer` package (src/). Preferred invocation
is `uv run ridecomposer ...`; this shim just puts src/ on the path and delegates,
for a zero-setup run. The original single-file vibecode is kept verbatim at
reference/compose.py for provenance.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from ridecomposer.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
