#!/usr/bin/env python3
"""Portable zstdcat fallback for systems without the zstd CLI."""

from __future__ import annotations

import sys

import zstandard


def main() -> int:
    decoder = None
    completed_frame = False
    try:
        while True:
            chunk = sys.stdin.buffer.read(1024 * 1024)
            if not chunk:
                break
            pending = chunk
            while pending:
                if decoder is None:
                    decoder = zstandard.ZstdDecompressor().decompressobj()
                sys.stdout.buffer.write(decoder.decompress(pending))
                if decoder.eof:
                    completed_frame = True
                    pending = decoder.unused_data
                    decoder = None
                else:
                    pending = b""
    except BrokenPipeError:
        return 0

    if decoder is not None or not completed_frame:
        print("incomplete zstd frame", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
