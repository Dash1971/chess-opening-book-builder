#!/usr/bin/env python3
"""Portable zstdcat fallback for systems without the zstd CLI."""

from __future__ import annotations

import shutil
import sys

import zstandard


def main() -> int:
    decompressor = zstandard.ZstdDecompressor()
    with decompressor.stream_reader(sys.stdin.buffer, read_across_frames=True) as reader:
        shutil.copyfileobj(reader, sys.stdout.buffer, length=1024 * 1024)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
