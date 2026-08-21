# Chess Opening Book Builder

Build rating-targeted [Polyglot](https://www.chessprogramming.org/PolyGlot)
opening books from real games in the public
[Lichess database](https://database.lichess.org/).

The builder is engine-independent. Its `.bin` files can be used by Maia,
Stockfish, and other chess engines or GUIs that support Polyglot books.

## What it does

- streams a selected portion of a monthly Lichess archive without a database
- builds several rating books in one pass
- groups games by average player rating within a configurable band
- filters by rapid, blitz, classical, or combined time-control groups
- scales move weights proportionally to observed move frequency
- keeps every observed move when at least 25 games reached its position
- writes standard Polyglot `.bin` files to `~/chess/books/`
- preserves a partial build when interrupted with Ctrl-C

## Requirements

- Linux or macOS
- Bash, `curl`, `zstdcat`, and Python 3
- 1–3 GB of free memory
- enough disk space for the selected archive prefix and generated books

Install the system dependencies:

```bash
# Ubuntu / Debian
sudo apt install curl zstd python3 python3-venv

# macOS with Homebrew
brew install zstd python
```

The first CPython run creates a private environment under
`~/.local/share/chess-opening-book-builder/` and installs `python-chess`.
If PyPy 3 already has `python-chess`, the builder uses it automatically.

## Quick start

```bash
git clone https://github.com/Dash1971/chess-opening-book-builder.git
cd chess-opening-book-builder
chmod +x build-books.sh
./build-books.sh
```

The interactive prompts select:

1. one or more target ratings from 600 to 2600
2. a time-control group
3. an archive-prefix size
4. a Lichess archive month

Books are written to `~/chess/books/`, with names such as:

```text
lichess_1400_all_2024-01.bin
lichess_1600_rapid_2024-01.bin
lichess_1800_blitz_rapid_2024-01.bin
```

Each book has a matching `.json` sidecar recording its source month and URL,
prefix byte count, rating parameters, thresholds, build status, and summary
statistics.

For a non-interactive Maia3 1600 Rapid imitation book:

```bash
./build-books.sh --defaults
# equivalent to:
./build-books.sh --preset maia3-1600-rapid
```

The preset uses rating 1600, Rapid, a ±50 rating band, at least 25 games per
emitted position, 40 plies maximum, a 200-point maximum opponent gap, and a
5 GiB January 2024 archive prefix.

All important parameters can be overridden:

```bash
./build-books.sh \
  --ratings 1400,1600,1800 \
  --speed rapid \
  --size-gb 5 \
  --month 2025-06 \
  --band-width 50 \
  --min-position-games 25 \
  --max-plies 40 \
  --max-elo-diff 200
```

Run `./build-books.sh --help` for the complete option list.

To change the output or persistent download-cache directory:

```bash
BOOKS_DIR=/path/to/books TMP_DIR=/path/to/temp ./build-books.sh
```

Downloaded prefixes are retained by default so another rating band can be
built without downloading the same data again. Pass `--clean` to remove the
cached prefix after a successful build. An interrupted run keeps the prefix,
writes any eligible partial books with `build_status: "interrupted"`, and exits
with status 130.

## How rating buckets work

For each game, the builder averages White and Black Elo. A target book accepts
the game when that average is within the configured band width, inclusive. A
single game can therefore contribute to more than one requested target book.

Only rated games in the selected time-control group are used. Games with more
than a 200-point difference between the players are excluded. The first 40
plies are collected, and a position is emitted only when at least 25 matching
games reached it. Every move observed in an emitted position is retained, and
weights are normalized independently within each position.

The Python builder lives in `book_builder.py`; `build-books.sh` provides the
interactive download and setup flow. Tests are under `tests/` and can be run
with:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
bash -n build-books.sh
```

GitHub Actions runs the Python tests on Linux and macOS and runs ShellCheck on
the Bash wrapper.

For real-corpus performance measurement, Polyglot verification, and held-out
move-distribution evaluation, see [docs/BENCHMARKING.md](docs/BENCHMARKING.md).

## Data and licensing

Lichess database exports are released under CC0. This project does not bundle
game archives or generated books. See [database.lichess.org](https://database.lichess.org/)
for source data and attribution details.

The project code is licensed under the MIT License.
