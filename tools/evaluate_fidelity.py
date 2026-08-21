#!/usr/bin/env python3
"""Evaluate a Polyglot book against held-out Lichess PGN games."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import TextIO

import chess
import chess.pgn
import chess.polyglot


def matches(headers: chess.pgn.Headers, parameters: dict[str, object]) -> bool:
    event = headers.get("Event", "").lower()
    speeds = parameters["speed_filters"]
    if "rated" not in event or not any(speed in event for speed in speeds):
        return False
    try:
        white = int(headers.get("WhiteElo", "0"))
        black = int(headers.get("BlackElo", "0"))
    except ValueError:
        return False
    if white <= 0 or black <= 0:
        return False
    if abs(white - black) > int(parameters["max_elo_diff"]):
        return False
    average = (white + black) // 2
    return abs(average - int(parameters["rating"])) <= int(parameters["band_width"])


def evaluate_stream(
    book_path: Path,
    metadata: dict[str, object],
    stream: TextIO,
    heldout_month: str,
) -> dict[str, object]:
    parameters = metadata["parameters"]
    max_plies = int(parameters["max_plies"])
    games_scanned = 0
    games_matched = 0
    observations = 0
    covered = 0
    zero_probability = 0
    log_loss_nats = 0.0
    by_ply: dict[int, Counter[str]] = defaultdict(Counter)
    actual_by_position: dict[int, Counter[str]] = defaultdict(Counter)
    position_ply: dict[int, int] = {}
    book_distributions: dict[int, dict[str, float]] = {}
    started = time.monotonic()

    with chess.polyglot.open_reader(book_path) as reader:
        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            games_scanned += 1
            if not matches(game.headers, parameters):
                continue
            moves = list(game.mainline_moves())
            if len(moves) < 6:
                continue
            games_matched += 1
            board = game.board()
            for ply, human_move in enumerate(moves[:max_plies], start=1):
                key = chess.polyglot.zobrist_hash(board)
                move_name = human_move.uci()
                observations += 1
                by_ply[ply]["observations"] += 1
                actual_by_position[key][move_name] += 1
                position_ply.setdefault(key, ply)

                entries = list(reader.find_all(board))
                if entries:
                    covered += 1
                    by_ply[ply]["covered"] += 1
                    total_weight = sum(entry.weight for entry in entries)
                    distribution = {
                        entry.move.uci(): entry.weight / total_weight for entry in entries
                    }
                    book_distributions.setdefault(key, distribution)
                    probability = distribution.get(move_name, 0.0)
                    if probability == 0:
                        zero_probability += 1
                        by_ply[ply]["zero_probability"] += 1
                    log_loss_nats -= math.log(max(probability, 1e-12))
                board.push(human_move)

    weighted_tv = 0.0
    weighted_positions = 0
    position_counts_by_ply: dict[int, list[int]] = defaultdict(list)
    for key, actual_counts in actual_by_position.items():
        count = sum(actual_counts.values())
        position_counts_by_ply[position_ply[key]].append(count)
        if key not in book_distributions:
            continue
        actual_distribution = {
            move: move_count / count for move, move_count in actual_counts.items()
        }
        book_distribution = book_distributions[key]
        moves = set(actual_distribution) | set(book_distribution)
        tv = 0.5 * sum(
            abs(actual_distribution.get(move, 0.0) - book_distribution.get(move, 0.0))
            for move in moves
        )
        weighted_tv += tv * count
        weighted_positions += count

    ply_report = {}
    for ply in sorted(by_ply):
        counts = by_ply[ply]
        ply_observations = counts["observations"]
        position_counts = position_counts_by_ply[ply]
        effective_games = (
            sum(count * count for count in position_counts) / sum(position_counts)
            if position_counts
            else 0.0
        )
        ply_report[str(ply)] = {
            "coverage": counts["covered"] / ply_observations,
            "covered": counts["covered"],
            "effective_position_games": round(effective_games, 3),
            "observations": ply_observations,
            "zero_probability": counts["zero_probability"],
        }

    elapsed = time.monotonic() - started
    return {
        "book": str(book_path),
        "book_source_month": metadata["source"]["month"],
        "coverage": covered / observations if observations else 0.0,
        "elapsed_seconds": round(elapsed, 3),
        "fallback_rate": 1 - covered / observations if observations else 1.0,
        "games_matched": games_matched,
        "games_per_second": games_scanned / elapsed if elapsed else 0.0,
        "games_scanned": games_scanned,
        "heldout_month": heldout_month,
        "observations": observations,
        "parameters": parameters,
        "ply": ply_report,
        "smoothed_cross_entropy_bits": (
            log_loss_nats / covered / math.log(2) if covered else None
        ),
        "weighted_total_variation": (
            weighted_tv / weighted_positions if weighted_positions else None
        ),
        "zero_probability_observations": zero_probability,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--pgn", default="-")
    parser.add_argument("--heldout-month", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    if args.pgn == "-":
        report = evaluate_stream(args.book, metadata, sys.stdin, args.heldout_month)
    else:
        with Path(args.pgn).open(encoding="utf-8", errors="replace") as stream:
            report = evaluate_stream(args.book, metadata, stream, args.heldout_month)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
