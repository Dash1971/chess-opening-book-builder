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
