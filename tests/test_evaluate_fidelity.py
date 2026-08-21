from __future__ import annotations

import io
import json

from book_builder import collect_stream, write_books
from tests.test_book_builder import config, make_game
from tools.evaluate_fidelity import evaluate_stream


def test_fidelity_report_matches_known_distribution(tmp_path) -> None:
    training = make_game("e4") * 15 + make_game("d4") * 5
    state = collect_stream(io.StringIO(training), config(tmp_path))
    [book] = write_books(state)
    metadata = json.loads(book.with_suffix(".json").read_text())

    heldout = make_game("e4") * 15 + make_game("d4") * 5
    report = evaluate_stream(book, metadata, io.StringIO(heldout), "2024-02")
    assert report["games_matched"] == 20
    assert report["coverage"] > 0
    assert report["weighted_total_variation"] == 0
    assert report["zero_probability_observations"] == 0
