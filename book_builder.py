#!/usr/bin/env python3
"""Build rating-targeted Polyglot opening books from a PGN stream."""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

import chess
import chess.pgn
import chess.polyglot


VERSION = "0.2.0"

PROMOTION_CODES = {
    chess.KNIGHT: 1,
    chess.BISHOP: 2,
    chess.ROOK: 3,
    chess.QUEEN: 4,
}


@dataclass(frozen=True)
class BuildConfig:
    ratings: tuple[int, ...]
    speeds: frozenset[str]
    speed_name: str
    output_dir: Path
    band_width: int = 100
    min_position_games: int = 25
    max_plies: int = 40
    max_elo_diff: int = 200
    month: str = "unknown"
    source_url: str = "unknown"
    source_bytes: int = 0
    partial_prefix: bool = True


@dataclass
class BuildState:
    config: BuildConfig
    move_counts: dict[int, dict[tuple[int, int], int]] = field(init=False)
    position_games: dict[int, dict[int, int]] = field(init=False)
    bucket_games: dict[int, int] = field(init=False)
    games_scanned: int = 0
    games_matched: int = 0

    def __post_init__(self) -> None:
        self.move_counts = {
            rating: defaultdict(int) for rating in self.config.ratings
        }
        self.position_games = {
            rating: defaultdict(int) for rating in self.config.ratings
        }
        self.bucket_games = {rating: 0 for rating in self.config.ratings}


def encode_polyglot_move(board: chess.Board, move: chess.Move) -> int:
    """Encode a move using Polyglot's 16-bit move representation."""
    to_file = chess.square_file(move.to_square)
    to_rank = chess.square_rank(move.to_square)
    from_file = chess.square_file(move.from_square)
    from_rank = chess.square_rank(move.from_square)

    if board.is_castling(move):
        to_file = 7 if to_file > from_file else 0

    promotion = PROMOTION_CODES.get(move.promotion, 0)
    return (
        to_file
        | (to_rank << 3)
        | (from_file << 6)
        | (from_rank << 9)
        | (promotion << 12)
    )


def matching_ratings(config: BuildConfig, average_elo: int) -> list[int]:
    return [
        rating
        for rating in config.ratings
        if abs(rating - average_elo) <= config.band_width
    ]


def event_matches(event: str, speeds: frozenset[str]) -> bool:
    lowered = event.lower()
    return "rated" in lowered and any(speed in lowered for speed in speeds)


def collect_stream(
    stream: TextIO, config: BuildConfig, state: BuildState | None = None
) -> BuildState:
    state = state or BuildState(config)
    started = time.monotonic()
    last_print = started

    while True:
        try:
            game = chess.pgn.read_game(stream)
        except (ValueError, UnicodeError):
            continue
        if game is None:
            break

        state.games_scanned += 1
        headers = game.headers
        if not event_matches(headers.get("Event", ""), config.speeds):
            continue

        try:
            white_elo = int(headers.get("WhiteElo", "0"))
            black_elo = int(headers.get("BlackElo", "0"))
        except ValueError:
            continue
        if white_elo <= 0 or black_elo <= 0:
            continue
        if abs(white_elo - black_elo) > config.max_elo_diff:
            continue

        ratings = matching_ratings(config, (white_elo + black_elo) // 2)
        if not ratings:
            continue

        mainline = list(game.mainline_moves())
        if len(mainline) < 6:
            continue

        state.games_matched += 1
        board = game.board()
        observations: list[tuple[int, int]] = []
        for move in mainline[: config.max_plies]:
            key = chess.polyglot.zobrist_hash(board)
            observations.append((key, encode_polyglot_move(board, move)))
            board.push(move)

        positions_in_game = {key for key, _ in observations}
        for rating in ratings:
            state.bucket_games[rating] += 1
            for key in positions_in_game:
                state.position_games[rating][key] += 1
            for observation in observations:
                state.move_counts[rating][observation] += 1

        now = time.monotonic()
        if now - last_print >= 3:
            elapsed = max(now - started, 0.001)
            rate = state.games_scanned / elapsed
            print(
                f"Scanned {state.games_scanned:,}; matched "
                f"{state.games_matched:,}; {rate:,.0f} games/s",
                file=sys.stderr,
                flush=True,
            )
            last_print = now

    return state


def entries_for_rating(state: BuildState, rating: int) -> list[tuple[int, int, int]]:
    config = state.config
    eligible_keys = {
        key
        for key, games in state.position_games[rating].items()
        if games >= config.min_position_games
    }
    if not eligible_keys:
        return []

    per_key_max: dict[int, int] = defaultdict(int)
    for (key, _move), count in state.move_counts[rating].items():
        if key in eligible_keys:
            per_key_max[key] = max(per_key_max[key], count)

    entries = [
        (key, move, max(1, round(count / per_key_max[key] * 65535)))
        for (key, move), count in state.move_counts[rating].items()
        if key in eligible_keys
    ]
    entries.sort(key=lambda entry: (entry[0], entry[1]))
    return entries


def output_path(config: BuildConfig, rating: int) -> Path:
    return config.output_dir / (
        f"lichess_{rating}_{config.speed_name}_{config.month}.bin"
    )


def metadata_path(book_path: Path) -> Path:
    return book_path.with_suffix(".json")


def write_json_atomic(destination: Path, payload: dict[str, object]) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as metadata:
            json.dump(payload, metadata, indent=2, sort_keys=True)
            metadata.write("\n")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def write_rating_book(
    state: BuildState, rating: int, build_status: str = "complete"
) -> Path | None:
    entries = entries_for_rating(state, rating)
    if not entries:
        return None

    destination = output_path(state.config, rating)
    temporary = destination.with_name(destination.name + ".tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("wb") as book:
            for key, move, weight in entries:
                book.write(struct.pack(">QHHi", key, move, weight, 0))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    config = state.config
    write_json_atomic(
        metadata_path(destination),
        {
            "artifact": destination.name,
            "build_status": build_status,
            "builder_version": VERSION,
            "parameters": {
                "band_width": config.band_width,
                "max_elo_diff": config.max_elo_diff,
                "max_plies": config.max_plies,
                "min_position_games": config.min_position_games,
                "rating": rating,
                "speed": config.speed_name,
                "speed_filters": sorted(config.speeds),
            },
            "source": {
                "bytes": config.source_bytes,
                "month": config.month,
                "partial_prefix": config.partial_prefix,
                "url": config.source_url,
            },
            "statistics": {
                "book_entries": len(entries),
                "games_in_rating_bucket": state.bucket_games[rating],
                "games_matched": state.games_matched,
                "games_scanned": state.games_scanned,
            },
        },
    )
    return destination


def write_books(state: BuildState, build_status: str = "complete") -> list[Path]:
    paths = []
    for rating in state.config.ratings:
        path = write_rating_book(state, rating, build_status)
        if path is not None:
            paths.append(path)
    return paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ratings", required=True)
    parser.add_argument("--speeds", required=True)
    parser.add_argument("--speed-name", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--band-width", type=int, default=100)
    parser.add_argument("--min-position-games", type=int, default=25)
    parser.add_argument("--max-plies", type=int, default=40)
    parser.add_argument("--max-elo-diff", type=int, default=200)
    parser.add_argument("--month", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-bytes", type=int, required=True)
    parser.add_argument("--full-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = BuildConfig(
        ratings=tuple(int(value) for value in args.ratings.split(",")),
        speeds=frozenset(args.speeds.split(",")),
        speed_name=args.speed_name,
        output_dir=args.output_dir.expanduser(),
        band_width=args.band_width,
        min_position_games=args.min_position_games,
        max_plies=args.max_plies,
        max_elo_diff=args.max_elo_diff,
        month=args.month,
        source_url=args.source_url,
        source_bytes=args.source_bytes,
        partial_prefix=not args.full_archive,
    )
    for label, value in (
        ("band width", config.band_width),
        ("minimum position games", config.min_position_games),
        ("maximum plies", config.max_plies),
        ("maximum Elo difference", config.max_elo_diff),
        ("source bytes", config.source_bytes),
    ):
        if value <= 0:
            raise SystemExit(f"{label} must be positive")

    state = BuildState(config)
    interrupted = False
    try:
        collect_stream(sys.stdin, config, state)
    except KeyboardInterrupt:
        interrupted = True
        print("Interrupted; writing a partial book from collected games.", file=sys.stderr)

    paths = write_books(state, "interrupted" if interrupted else "complete")
    print(f"Scanned: {state.games_scanned:,} games")
    print(f"Matched: {state.games_matched:,} games")
    for path in paths:
        print(path)
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
