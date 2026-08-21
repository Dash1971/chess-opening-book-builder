#!/usr/bin/env bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOKS_DIR="${BOOKS_DIR:-$HOME/chess/books}"
TMP_DIR="${TMP_DIR:-$HOME/chess/bookbuild-tmp}"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

usage() {
    cat <<'EOF'
Usage: ./build-books.sh [--defaults]

Build rating-targeted Polyglot opening books from a streamed portion of a
Lichess monthly PGN archive. With --defaults, use the documented defaults.

Optional environment variables:
  BOOKS_DIR  Output directory (default: ~/chess/books)
  TMP_DIR    Temporary download directory (default: ~/chess/bookbuild-tmp)
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi
if [[ $# -gt 0 && "${1:-}" != "--defaults" ]]; then
    echo "Unknown option: $1" >&2
    usage >&2
    exit 2
fi

DEFAULT_RATINGS="1400,1600,1800"
DEFAULT_SPEED=5
DEFAULT_SIZE=2
DEFAULT_MONTH="2024-01"

echo ""
echo -e "${BOLD}${CYAN}Lichess Opening Book Builder${RESET}"
echo ""

if [[ "${1:-}" == "--defaults" ]]; then
    RATINGS="$DEFAULT_RATINGS"
    SPEED_CHOICE="$DEFAULT_SPEED"
    SIZE_CHOICE="$DEFAULT_SIZE"
    MONTH="$DEFAULT_MONTH"
else
    echo -e "${BOLD}Step 1 of 4: target rating(s)${RESET}"
    read -p "Ratings [${DEFAULT_RATINGS}]: " RATINGS
    RATINGS="${RATINGS:-$DEFAULT_RATINGS}"

    echo -e "${BOLD}Step 2 of 4: time control${RESET}"
    echo "1) Rapid  2) Blitz  3) Classical  4) Blitz + Rapid  5) All"
    read -p "Choice [${DEFAULT_SPEED}]: " SPEED_CHOICE
    SPEED_CHOICE="${SPEED_CHOICE:-$DEFAULT_SPEED}"

    echo -e "${BOLD}Step 3 of 4: data size${RESET}"
    echo "1) 2 GB  2) 5 GB  3) 10 GB"
    read -p "Choice [${DEFAULT_SIZE}]: " SIZE_CHOICE
    SIZE_CHOICE="${SIZE_CHOICE:-$DEFAULT_SIZE}"

    echo -e "${BOLD}Step 4 of 4: Lichess archive month${RESET}"
    read -p "Month [${DEFAULT_MONTH}]: " MONTH
    MONTH="${MONTH:-$DEFAULT_MONTH}"
fi

IFS=',' read -ra RATING_ARRAY <<< "$RATINGS"
VALID_RATINGS=()
for rating in "${RATING_ARRAY[@]}"; do
    rating=$(echo "$rating" | tr -d ' ')
    if [[ "$rating" =~ ^[0-9]+$ ]] && [[ $((rating % 100)) -eq 0 ]] \
        && [[ $rating -ge 600 ]] && [[ $rating -le 2600 ]]; then
        VALID_RATINGS+=("$rating")
    else
        echo -e "${RED}Invalid rating: $rating${RESET}" >&2
        exit 1
    fi
done
RATINGS=$(IFS=','; echo "${VALID_RATINGS[*]}")

case "$SPEED_CHOICE" in
    1) SPEED_NAME="rapid"; SPEED_FILTER="rapid" ;;
    2) SPEED_NAME="blitz"; SPEED_FILTER="blitz" ;;
    3) SPEED_NAME="classical"; SPEED_FILTER="classical" ;;
    4) SPEED_NAME="blitz_rapid"; SPEED_FILTER="blitz,rapid" ;;
    5) SPEED_NAME="all"; SPEED_FILTER="blitz,rapid,classical" ;;
    *) echo -e "${RED}Invalid speed choice${RESET}" >&2; exit 1 ;;
esac

case "$SIZE_CHOICE" in
    1) MAX_GB=2 ;;
    2) MAX_GB=5 ;;
    3) MAX_GB=10 ;;
    *) echo -e "${RED}Invalid size choice${RESET}" >&2; exit 1 ;;
esac
MAX_BYTES=$((MAX_GB * 1073741824))

if ! [[ "$MONTH" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
    echo -e "${RED}Invalid month: $MONTH${RESET}" >&2
    exit 1
fi
MONTH_YEAR="${MONTH%-*}"
MONTH_NUMBER="${MONTH#*-}"
if [[ $MONTH_YEAR -lt 2013 ]] || [[ $MONTH_YEAR -gt 2099 ]] \
    || [[ $((10#$MONTH_NUMBER)) -lt 1 ]] || [[ $((10#$MONTH_NUMBER)) -gt 12 ]]; then
    echo -e "${RED}Invalid month: $MONTH${RESET}" >&2
    exit 1
fi

OS="$(uname -s)"
install_hint() {
    local package="$1"
    if [[ "$OS" == "Darwin" ]]; then
        echo "Install $package with: brew install $package" >&2
    else
        echo "Install $package with: sudo apt install $package" >&2
    fi
    exit 1
}

command -v zstdcat >/dev/null 2>&1 || install_hint zstd
command -v curl >/dev/null 2>&1 || install_hint curl

if command -v pypy3 >/dev/null 2>&1 \
    && pypy3 -c "import chess; import chess.polyglot; import chess.pgn" 2>/dev/null; then
    PYTHON_CMD="pypy3"
else
    VENV="${XDG_DATA_HOME:-$HOME/.local/share}/chess-opening-book-builder/venv"
    if [[ ! -d "$VENV" ]]; then
        command -v python3 >/dev/null 2>&1 || install_hint python3
        python3 -m venv "$VENV" || {
            echo "Could not create $VENV. Install python3-venv and retry." >&2
            exit 1
        }
        "$VENV/bin/python" -m pip install --disable-pip-version-check \
            "python-chess>=1.999,<2"
    fi
    PYTHON_CMD="$VENV/bin/python"
fi

mkdir -p "$BOOKS_DIR" "$TMP_DIR"
CHUNK="$TMP_DIR/lichess-${MONTH}.pgn.zst"
DB_URL="https://database.lichess.org/standard/lichess_db_standard_rated_${MONTH}.pgn.zst"
file_size() { wc -c < "$1" 2>/dev/null | tr -d ' ' || echo 0; }

echo -e "${BOLD}Downloading ${MAX_GB} GB from ${MONTH}${RESET}"
if [[ -f "$CHUNK" ]] && [[ $(file_size "$CHUNK") -gt $((MAX_BYTES / 2)) ]]; then
    echo "Using existing download: $CHUNK"
else
    HTTP=$(curl -sI -o /dev/null -w "%{http_code}" "$DB_URL")
    if [[ "$HTTP" != "200" ]]; then
        echo "HTTP $HTTP: Lichess archive $MONTH is unavailable" >&2
        exit 1
    fi
    curl -L --range "0-$((MAX_BYTES - 1))" --progress-bar \
        --user-agent "chess-opening-book-builder/1.0" -o "$CHUNK" "$DB_URL"
fi

if ! zstdcat "$CHUNK" 2>/dev/null | head -c 500 | grep -q "\[Event"; then
    echo "Download does not begin with valid PGN data" >&2
    exit 1
fi

echo -e "${BOLD}Building books${RESET}"
set +e
zstdcat "$CHUNK" 2>/dev/null | "$PYTHON_CMD" -u "$SCRIPT_DIR/book_builder.py" \
    --ratings "$RATINGS" \
    --speeds "$SPEED_FILTER" \
    --speed-name "$SPEED_NAME" \
    --output-dir "$BOOKS_DIR" \
    --band-width 100 \
    --min-position-games 25 \
    --max-plies 40 \
    --max-elo-diff 200
BUILD_RESULT=$?
set -e

if [[ $BUILD_RESULT -eq 0 ]]; then
    rm -f "$CHUNK"
    echo -e "${GREEN}Books built in $BOOKS_DIR${RESET}"
else
    echo -e "${YELLOW}Build stopped with status $BUILD_RESULT; download retained at $CHUNK${RESET}" >&2
fi
exit "$BUILD_RESULT"
