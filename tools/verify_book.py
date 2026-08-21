#!/usr/bin/env python3
"""Verify Polyglot format invariants and legal move decoding."""

from __future__ import annotations

import argparse
import json
import random
import struct
from pathlib import Path

import chess
import chess.polyglot


def verify_book(path: Path, random_walks: int = 100) -> dict[str, object]:
    data = path.read_bytes()
    errors: list[str] = []
    if len(data) % 16:
        errors.append("file size is not a multiple of 16 bytes")

    records = [
        struct.unpack(">QHHi", data[offset : offset + 16])
        for offset in range(0, len(data) - len(data) % 16, 16)
    ]
    keys = [record[0] for record in records]
    if keys != sorted(keys):
        errors.append("records are not sorted by Zobrist key")
    pairs = [(record[0], record[1]) for record in records]
    if len(pairs) != len(set(pairs)):
        errors.append("duplicate key/move records found")
    if any(not 1 <= record[2] <= 65535 for record in records):
        errors.append("weight outside 1..65535")

    rng = random.Random(0)
    legal_moves_checked = 0
    with chess.polyglot.open_reader(path) as reader:
        for _ in range(random_walks):
            board = chess.Board()
            for _ply in range(80):
                entries = list(reader.find_all(board))
                if not entries:
                    break
                entry = rng.choices(entries, weights=[item.weight for item in entries])[0]
                if entry.move not in board.legal_moves:
                    errors.append(f"illegal decoded move: {entry.move.uci()}")
                    break
                legal_moves_checked += 1
                board.push(entry.move)

    return {
        "book": str(path),
        "bytes": len(data),
        "entries": len(records),
        "errors": errors,
        "legal_moves_checked": legal_moves_checked,
        "valid": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("book", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--random-walks", type=int, default=100)
    args = parser.parse_args()
    report = verify_book(args.book, args.random_walks)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
