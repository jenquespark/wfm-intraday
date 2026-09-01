#!/usr/bin/env python3
"""Generate synthetic contact centre sample data."""
import sys
from reforecast.sample_data import generate_synthetic_data

if __name__ == "__main__":
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    generate_synthetic_data(output_dir)