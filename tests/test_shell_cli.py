from __future__ import annotations

import os
import http.server
import functools
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import zstandard


ROOT = Path(__file__).resolve().parents[1]


def test_help_contains_source_examples() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "build-books.sh"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--source LOCATION" in result.stdout
    assert "--source /data/lichess_games.pgn.zst" in result.stdout
    assert "--source https://example.org/games.pgn.zst" in result.stdout


def test_local_source_is_validated_without_copying(tmp_path: Path) -> None:
    archive = tmp_path / "existing.pgn.zst"
    pgn = (
        '[Event "Rated Rapid game"]\n'
        '[WhiteElo "1600"]\n'
        '[BlackElo "1600"]\n\n'
        '1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0\n'
    ).encode()
    archive.write_bytes(zstandard.ZstdCompressor().compress(pgn))
    original = archive.read_bytes()
    managed_venv = tmp_path / "xdg" / "chess-opening-book-builder" / "venv"
    managed_venv.parent.mkdir(parents=True)
    managed_venv.symlink_to(Path(sys.prefix))
    env = os.environ.copy()
    env.update(
        {
            "BOOKS_DIR": str(tmp_path / "books"),
            "TMP_DIR": str(tmp_path / "cache"),
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
        }
    )
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "build-books.sh"),
            "--defaults",
            "--source",
            str(archive),
            "--month",
            "2025-06",
            "--download-only",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "Validated archive prefix" in result.stdout
    assert archive.read_bytes() == original
    assert not list((tmp_path / "cache").glob("*.pgn.zst"))


def test_remote_source_downloads_complete_file_by_default(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    archive = served / "games.pgn.zst"
    pgn = (
        '[Event "Rated Rapid game"]\n'
        '[WhiteElo "1600"]\n'
        '[BlackElo "1600"]\n\n'
        '1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0\n'
    ).encode()
    archive.write_bytes(zstandard.ZstdCompressor().compress(pgn))

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(served)
    )
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        managed_venv = tmp_path / "xdg" / "chess-opening-book-builder" / "venv"
        managed_venv.parent.mkdir(parents=True)
        managed_venv.symlink_to(Path(sys.prefix))
        env = os.environ.copy()
        env.update(
            {
                "BOOKS_DIR": str(tmp_path / "books"),
                "TMP_DIR": str(tmp_path / "cache"),
                "XDG_DATA_HOME": str(tmp_path / "xdg"),
            }
        )
        result = subprocess.run(
            [
                "bash",
                str(ROOT / "build-books.sh"),
                "--defaults",
                "--source",
                f"http://127.0.0.1:{server.server_address[1]}/{archive.name}",
                "--month",
                "2025-06",
                "--download-only",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    assert "Downloading complete archive" in result.stdout
    cached = list((tmp_path / "cache").glob("source-*-full.pgn.zst"))
    assert len(cached) == 1
    assert cached[0].read_bytes() == archive.read_bytes()
