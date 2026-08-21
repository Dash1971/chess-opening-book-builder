# Chess Opening Book Builder

Build rating-targeted [Polyglot](https://www.chessprogramming.org/Polyglot)
opening books from real games in the public
[Lichess database](https://database.lichess.org/).

The builder is engine-independent. Its `.bin` files can be used by Maia,
Stockfish, and other chess engines or GUIs that support Polyglot books.

## What it does

- streams a selected portion of a monthly Lichess archive without a database
- builds several rating books in one pass
- groups games by average player rating within ±100 of each target
- filters by rapid, blitz, classical, or combined time-control groups
- scales move weights proportionally to observed move frequency
- keeps every observed move when at least 25 games reached its position
- writes standard Polyglot `.bin` files to `~/chess/books/`
- preserves a partial build when interrupted with Ctrl-C

## Requirements

- Linux or macOS
- Bash, `curl`, `zstdcat`, and Python 3
- 1–3 GB of free memory
- 2–10 GB of temporary disk space, depending on the selected download size

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

The prompts select:

1. one or more target ratings from 600 to 2600
2. a time-control group
3. a 2, 5, or 10 GB archive slice
4. a Lichess archive month

Books are written to `~/chess/books/`, with names such as:

```text
lichess_1400_all.bin
lichess_1600_rapid.bin
lichess_1800_blitz_rapid.bin
```

For a non-interactive run using the documented defaults:

```bash
./build-books.sh --defaults
```

To change the output or temporary directory:

```bash
BOOKS_DIR=/path/to/books TMP_DIR=/path/to/temp ./build-books.sh
```

## How rating buckets work

For each game, the builder averages White and Black Elo. A target book accepts
the game when that average is within 100 points of the target, inclusive. A
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
```

## Data and licensing

Lichess database exports are released under CC0. This project does not bundle
game archives or generated books. See [database.lichess.org](https://database.lichess.org/)
for source data and attribution details.

The project code is licensed under the MIT License.
