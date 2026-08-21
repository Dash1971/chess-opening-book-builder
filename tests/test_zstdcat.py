from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import zstandard


def test_python_zstdcat_round_trip() -> None:
    source = (b"[Event test]\n\n1. e4 e5\n" * 1000)
    compressed = zstandard.ZstdCompressor().compress(source)
    script = Path(__file__).parents[1] / "tools" / "zstdcat.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        input=compressed,
        capture_output=True,
        check=True,
    )
    assert result.stdout == source


def test_python_zstdcat_handles_concatenated_frames() -> None:
    first = b"first frame\n" * 100
    second = b"second frame\n" * 100
    compressor = zstandard.ZstdCompressor()
    compressed = compressor.compress(first) + compressor.compress(second)
    script = Path(__file__).parents[1] / "tools" / "zstdcat.py"
    result = subprocess.run(
        [sys.executable, str(script)], input=compressed, capture_output=True
    )
    assert result.returncode == 0
    assert result.stdout == first + second


def test_python_zstdcat_reports_truncated_frame() -> None:
    source = b"opening data\n" * 100_000
    compressed = zstandard.ZstdCompressor().compress(source)
    script = Path(__file__).parents[1] / "tools" / "zstdcat.py"
    result = subprocess.run(
        [sys.executable, str(script)], input=compressed[:-1], capture_output=True
    )
    assert result.returncode == 3
    assert result.stdout
    assert b"incomplete zstd frame" in result.stderr
