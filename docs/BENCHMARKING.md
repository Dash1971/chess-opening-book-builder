# Benchmarking and fidelity evaluation

Use reproducible archive prefixes and keep generated reports under an ignored
local directory such as `reports/`. Do not commit downloaded PGN data or
generated books.

## 1. Build the baseline

```bash
./build-books.sh --preset maia3-1600-rapid
```

The matching JSON sidecar records elapsed time, peak resident memory, games
scanned and matched, output entries, source bytes, and coverage statistics by
ply.

## 2. Verify the Polyglot output

```bash
mkdir -p reports
.venv/bin/python tools/verify_book.py \
  ~/chess/books/lichess_1600_rapid_2024-01.bin \
  --output reports/verify-1600-rapid-2024-01.json
```

The verifier checks record size, key ordering, duplicate key/move pairs,
weight bounds, and legal moves during deterministic random walks.

## 3. Download a held-out month

```bash
./build-books.sh \
  --download-only \
  --month 2024-02 \
  --size-gb 1
```

This writes and validates
`~/chess/bookbuild-cache/lichess-2024-02-1gb.pgn.zst` without building another
book.

## 4. Evaluate held-out fidelity

When `zstdcat` is installed:

```bash
zstdcat ~/chess/bookbuild-cache/lichess-2024-02-1gb.pgn.zst 2>/dev/null \
  | .venv/bin/python tools/evaluate_fidelity.py \
      --book ~/chess/books/lichess_1600_rapid_2024-01.bin \
      --metadata ~/chess/books/lichess_1600_rapid_2024-01.json \
      --pgn - \
      --heldout-month 2024-02 \
      --output reports/fidelity-1600-rapid-2024-02.json
```

Without the system zstd tools, use the portable fallback:

```bash
.venv/bin/python tools/zstdcat.py \
  < ~/chess/bookbuild-cache/lichess-2024-02-1gb.pgn.zst \
  | .venv/bin/python tools/evaluate_fidelity.py \
      --book ~/chess/books/lichess_1600_rapid_2024-01.bin \
      --metadata ~/chess/books/lichess_1600_rapid_2024-01.json \
      --pgn - \
      --heldout-month 2024-02 \
      --output reports/fidelity-1600-rapid-2024-02.json
```

The report includes coverage and fallback rates, smoothed cross-entropy,
weighted total-variation distance, unseen held-out moves, effective position
sample size, and coverage by ply.

The held-out evaluator uses the rating band, speed filters, maximum Elo gap,
and maximum plies recorded in the book's provenance sidecar.
