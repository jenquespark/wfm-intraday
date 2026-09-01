#!/usr/bin/env python3
"""Backward-compatible entry point.  Delegates to ``wfm-reforecast`` CLI."""
import sys
from reforecast.cli.main import main

if __name__ == "__main__":
    sys.exit(main())