from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import chess
import chess.polyglot
import pytest

import book_builder
from book_builder import (
    BuildConfig,
    collect_stream,
    encode_polyglot_move,
    entries_for_rating,
    write_books,
)
from tools.verify_book import verify_book


def make_game(first_move: str, white: int = 1600, black: int = 1600) -> str:
    line = {
        "e4": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0",
        "d4": "1. d4 d5 2. c4 e6 3. Nc3 Nf6 1-0",
        "a3": "1. a3 e5 2. e4 Nf6 3. Nc3 d5 1-0",
    }[first_move]
    return (
        '[Event "Rated Rapid game"]\n'
        f'[WhiteElo "{white}"]\n'
        f'[BlackElo "{black}"]\n'
        '[Result "1-0"]\n\n'
        f"{line}\n\n"
    )


def config(tmp_path: Path, **overrides: int) -> BuildConfig:
    values = {
        "band_width": 50,
        "min_position_games": 1,
        "max_plies": 40,
        "max_elo_diff": 200,
    }
    values.update(overrides)
    return BuildConfig(
        ratings=(1600,),
        speeds=frozenset({"rapid"}),
        speed_name="rapid",
        output_dir=tmp_path,
        **values,
    )


def test_castling_uses_rook_square() -> None:
    board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    encoded = encode_polyglot_move(board, chess.Move.from_uci("e1g1"))
    assert encoded & 0x7 == chess.FILE_NAMES.index("h")


def test_non_castling_e_file_move_is_not_rewritten() -> None:
    board = chess.Board("k7/8/8/8/8/8/8/K3R3 w - - 0 1")
    move = chess.Move.from_uci("e1g1")
    assert move in board.legal_moves
    encoded = encode_polyglot_move(board, move)
    assert encoded & 0x7 == chess.FILE_NAMES.index("g")


def test_weights_are_normalized_per_position(tmp_path: Path) -> None:
    pgn = make_game("e4") * 15 + make_game("d4") * 5
    state = collect_stream(io.StringIO(pgn), config(tmp_path))
    root = chess.polyglot.zobrist_hash(chess.Board())
    root_entries = {
        move: weight
        for key, move, weight in entries_for_rating(state, 1600)
        if key == root
    }
    e4 = encode_polyglot_move(chess.Board(), chess.Move.from_uci("e2e4"))
    d4 = encode_polyglot_move(chess.Board(), chess.Move.from_uci("d2d4"))
    assert root_entries == {e4: 65535, d4: 21845}

    after_d4 = chess.Board()
    after_d4.push_uci("d2d4")
    after_d4_key = chess.polyglot.zobrist_hash(after_d4)
    d5 = encode_polyglot_move(after_d4, chess.Move.from_uci("d7d5"))
    assert {
        move: weight
        for key, move, weight in entries_for_rating(state, 1600)
        if key == after_d4_key
    } == {d5: 65535}


def test_keeps_single_observed_move_in_eligible_position(tmp_path: Path) -> None:
    pgn = make_game("e4") * 24 + make_game("a3")
    state = collect_stream(
        io.StringIO(pgn), config(tmp_path, min_position_games=25)
    )
    root = chess.polyglot.zobrist_hash(chess.Board())
    root_moves = {
        move
        for key, move, _weight in entries_for_rating(state, 1600)
        if key == root
    }
    a3 = encode_polyglot_move(chess.Board(), chess.Move.from_uci("a2a3"))
    assert a3 in root_moves


def test_max_elo_difference_filters_mismatches(tmp_path: Path) -> None:
    pgn = make_game("e4", white=1200, black=2000)
    state = collect_stream(io.StringIO(pgn), config(tmp_path))
    assert state.games_matched == 0


def test_written_book_invariants_and_legal_moves(tmp_path: Path) -> None:
    state = collect_stream(io.StringIO(make_game("e4") * 3), config(tmp_path))
    [path] = write_books(state)
    data = path.read_bytes()
    assert len(data) % 16 == 0
    records = [struct.unpack(">QHHi", data[i : i + 16]) for i in range(0, len(data), 16)]
    assert [(key, move) for key, move, _weight, _learn in records] == sorted(
        (key, move) for key, move, _weight, _learn in records
    )
    assert len({(key, move) for key, move, _weight, _learn in records}) == len(records)
    assert all(1 <= weight <= 65535 for _key, _move, weight, _learn in records)
    assert not path.with_name(path.name + ".tmp").exists()
    metadata = json.loads(path.with_suffix(".json").read_text())
    assert metadata["build_status"] == "complete"
    assert metadata["parameters"]["min_position_games"] == 1
    assert metadata["statistics"]["book_entries"] == len(records)

    with chess.polyglot.open_reader(path) as reader:
        entries = list(reader.find_all(chess.Board()))
    assert entries
    assert all(entry.move in chess.Board().legal_moves for entry in entries)
    assert verify_book(path, random_walks=10)["valid"] is True


def test_interruption_writes_partial_metadata_and_exits_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_collect = book_builder.collect_stream

    def interrupt_after_games(stream, build_config, state):
        original_collect(io.StringIO(make_game("e4") * 25), build_config, state)
        raise KeyboardInterrupt

    monkeypatch.setattr(book_builder, "collect_stream", interrupt_after_games)
    result = book_builder.main(
        [
            "--ratings", "1600",
            "--speeds", "rapid",
            "--speed-name", "rapid",
            "--output-dir", str(tmp_path),
            "--band-width", "50",
            "--min-position-games", "25",
            "--max-plies", "40",
            "--max-elo-diff", "200",
            "--month", "2024-01",
            "--source-url", "https://example.invalid/archive.pgn.zst",
            "--source-bytes", "1024",
        ]
    )
    assert result == 130
    metadata_files = list(tmp_path.glob("*.json"))
    assert len(metadata_files) == 1
    assert json.loads(metadata_files[0].read_text())["build_status"] == "interrupted"
