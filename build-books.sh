#!/usr/bin/env bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOKS_DIR="${BOOKS_DIR:-$HOME/chess/books}"
CACHE_DIR="${TMP_DIR:-$HOME/chess/bookbuild-cache}"

if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'
    YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'
else
    GREEN=''; CYAN=''; RED=''; YELLOW=''; BOLD=''; RESET=''
fi

usage() {
    cat <<'EOF'
Usage: ./build-books.sh [options]

Options:
  --defaults                     Use the Maia3 1600 Rapid preset
  --preset maia3-1600-rapid      Use the Maia3 1600 Rapid preset
  --ratings LIST                 Comma-separated ratings (600-2600)
  --speed NAME                   rapid, blitz, classical, blitz-rapid, or all
  --size-gb N                    Prefix size in GiB (default: 5)
  --month YYYY-MM                Lichess archive month
  --source LOCATION              Local .pgn.zst path or HTTP(S) archive URL
  --band-width N                 Rating half-width (default: 50)
  --min-position-games N         Minimum games reaching a position (default: 25)
  --max-plies N                  Maximum collected plies (default: 30)
  --max-elo-diff N               Maximum player rating difference (default: 200)
  --clean                        Delete downloaded cache after success (never local source)
  --download-only                Cache and validate the prefix without building
  -h, --help                     Show this help

Environment:
  BOOKS_DIR  Output directory (default: ~/chess/books)
  TMP_DIR    Persistent download cache (default: ~/chess/bookbuild-cache)

Examples:
  ./build-books.sh --preset maia3-1600-rapid
  ./build-books.sh --defaults --month 2025-06 --size-gb 10
  ./build-books.sh --defaults --source /data/lichess_games.pgn.zst --month 2025-06
  ./build-books.sh --defaults --source https://example.org/games.pgn.zst \
    --month 2025-06 --size-gb 5
EOF
}

RATINGS="1600"
SPEED_NAME="rapid"
MAX_GB=5
MONTH="2024-01"
BAND_WIDTH=50
MIN_POSITION_GAMES=25
MAX_PLIES=30
MAX_ELO_DIFF=200
CLEAN=0
DOWNLOAD_ONLY=0
NON_INTERACTIVE=0
SOURCE=""
SIZE_GB_SET=0

need_value() {
    if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Missing value for $1" >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --defaults)
            NON_INTERACTIVE=1
            shift
            ;;
        --preset)
            need_value "$@"
            if [[ "$2" != "maia3-1600-rapid" ]]; then
                echo "Unknown preset: $2" >&2
                exit 2
            fi
            NON_INTERACTIVE=1
            shift 2
            ;;
        --ratings)
            need_value "$@"; RATINGS="$2"; NON_INTERACTIVE=1; shift 2 ;;
        --speed)
            need_value "$@"; SPEED_NAME="$2"; NON_INTERACTIVE=1; shift 2 ;;
        --size-gb)
            need_value "$@"; MAX_GB="$2"; SIZE_GB_SET=1; NON_INTERACTIVE=1; shift 2 ;;
        --month)
            need_value "$@"; MONTH="$2"; NON_INTERACTIVE=1; shift 2 ;;
        --source)
            need_value "$@"; SOURCE="$2"; NON_INTERACTIVE=1; shift 2 ;;
        --band-width)
            need_value "$@"; BAND_WIDTH="$2"; NON_INTERACTIVE=1; shift 2 ;;
        --min-position-games)
            need_value "$@"; MIN_POSITION_GAMES="$2"; NON_INTERACTIVE=1; shift 2 ;;
        --max-plies)
            need_value "$@"; MAX_PLIES="$2"; NON_INTERACTIVE=1; shift 2 ;;
        --max-elo-diff)
            need_value "$@"; MAX_ELO_DIFF="$2"; NON_INTERACTIVE=1; shift 2 ;;
        --clean)
            CLEAN=1; shift ;;
        --download-only)
            DOWNLOAD_ONLY=1; NON_INTERACTIVE=1; shift ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

printf '\n%bLichess Opening Book Builder%b\n\n' "$BOLD$CYAN" "$RESET"

if [[ $NON_INTERACTIVE -eq 0 ]]; then
    read -r -p "Ratings [$RATINGS]: " input
    RATINGS="${input:-$RATINGS}"
    read -r -p "Speed (rapid/blitz/classical/blitz-rapid/all) [$SPEED_NAME]: " input
    SPEED_NAME="${input:-$SPEED_NAME}"
    read -r -p "Data prefix in GiB [$MAX_GB]: " input
    MAX_GB="${input:-$MAX_GB}"
    read -r -p "Archive month [$MONTH]: " input
    MONTH="${input:-$MONTH}"
fi

IFS=',' read -ra RATING_ARRAY <<< "$RATINGS"
VALID_RATINGS=()
for rating in "${RATING_ARRAY[@]}"; do
    rating=$(printf '%s' "$rating" | tr -d ' ')
    if [[ "$rating" =~ ^[0-9]+$ ]] && [[ $((rating % 100)) -eq 0 ]] \
        && [[ $rating -ge 600 ]] && [[ $rating -le 2600 ]]; then
        VALID_RATINGS+=("$rating")
    else
        printf '%bInvalid rating: %s%b\n' "$RED" "$rating" "$RESET" >&2
        exit 1
    fi
done
RATINGS=$(IFS=','; printf '%s' "${VALID_RATINGS[*]}")

case "$SPEED_NAME" in
    rapid) SPEED_FILTER="rapid" ;;
    blitz) SPEED_FILTER="blitz" ;;
    classical) SPEED_FILTER="classical" ;;
    blitz-rapid|blitz_rapid)
        SPEED_NAME="blitz_rapid"; SPEED_FILTER="blitz,rapid" ;;
    all) SPEED_FILTER="blitz,rapid,classical" ;;
    *) echo "Invalid speed: $SPEED_NAME" >&2; exit 1 ;;
esac

for number in "$MAX_GB" "$BAND_WIDTH" "$MIN_POSITION_GAMES" "$MAX_PLIES" "$MAX_ELO_DIFF"; do
    if ! [[ "$number" =~ ^[1-9][0-9]*$ ]]; then
        echo "Numeric options must be positive integers" >&2
        exit 1
    fi
done

if ! [[ "$MONTH" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
    echo "Invalid month: $MONTH" >&2
    exit 1
fi
MONTH_YEAR="${MONTH%-*}"
MONTH_NUMBER="${MONTH#*-}"
if [[ $MONTH_YEAR -lt 2013 ]] || [[ $MONTH_YEAR -gt 2099 ]] \
    || [[ $((10#$MONTH_NUMBER)) -lt 1 ]] || [[ $((10#$MONTH_NUMBER)) -gt 12 ]]; then
    echo "Invalid month: $MONTH" >&2
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
command -v curl >/dev/null 2>&1 || install_hint curl

if command -v pypy3 >/dev/null 2>&1 \
    && pypy3 -c "import chess; import chess.polyglot; import chess.pgn" 2>/dev/null; then
    PYTHON_CMD="pypy3"
else
    VENV="${XDG_DATA_HOME:-$HOME/.local/share}/chess-opening-book-builder/venv"
    command -v python3 >/dev/null 2>&1 || install_hint python3
    if [[ ! -x "$VENV/bin/python" ]]; then
        python3 -m venv "$VENV" || {
            echo "Could not create $VENV. Install python3-venv and retry." >&2
            exit 1
        }
    fi
    if ! "$VENV/bin/python" -c "import chess; import chess.polyglot; import chess.pgn; import zstandard" 2>/dev/null; then
        "$VENV/bin/python" -m pip install --disable-pip-version-check \
            -r "$SCRIPT_DIR/requirements.txt"
    fi
    PYTHON_CMD="$VENV/bin/python"
fi

if command -v zstdcat >/dev/null 2>&1; then
    ZSTDCAT_CMD=(zstdcat)
    DECODER_NAME="zstd-cli"
else
    if ! "$PYTHON_CMD" -c "import zstandard" 2>/dev/null; then
        "$PYTHON_CMD" -m pip install --disable-pip-version-check "zstandard>=0.23,<1"
    fi
    ZSTDCAT_CMD=("$PYTHON_CMD" "$SCRIPT_DIR/tools/zstdcat.py")
    DECODER_NAME="python-zstandard"
fi

mkdir -p "$BOOKS_DIR" "$CACHE_DIR"
MAX_BYTES=$((MAX_GB * 1073741824))
file_size() { wc -c < "$1" 2>/dev/null | tr -d ' ' || echo 0; }

SOURCE_IS_LOCAL=0
SOURCE_REMOTE_FULL=0
FULL_ARCHIVE=0
if [[ -z "$SOURCE" ]]; then
    SOURCE_URL="https://database.lichess.org/standard/lichess_db_standard_rated_${MONTH}.pgn.zst"
    CHUNK="$CACHE_DIR/lichess-${MONTH}-${MAX_GB}gb.pgn.zst"
elif [[ "$SOURCE" =~ ^https?:// ]]; then
    SOURCE_URL="$SOURCE"
    SOURCE_ID=$(printf '%s' "$SOURCE_URL" | cksum | awk '{print $1}')
    if [[ $SIZE_GB_SET -eq 1 ]]; then
        CHUNK="$CACHE_DIR/source-${SOURCE_ID}-${MAX_GB}gb.pgn.zst"
    else
        SOURCE_REMOTE_FULL=1
        FULL_ARCHIVE=1
        CHUNK="$CACHE_DIR/source-${SOURCE_ID}-full.pgn.zst"
    fi
else
    if [[ "$SOURCE" == file://* ]]; then
        SOURCE="${SOURCE#file://}"
    fi
    if [[ ! -f "$SOURCE" ]]; then
        echo "Local source file does not exist: $SOURCE" >&2
        exit 1
    fi
    SOURCE_DIR=$(cd "$(dirname "$SOURCE")" && pwd -P)
    CHUNK="$SOURCE_DIR/$(basename "$SOURCE")"
    SOURCE_URL="file://$CHUNK"
    SOURCE_IS_LOCAL=1
    FULL_ARCHIVE=1
    MAX_BYTES=$(file_size "$CHUNK")
fi

PART="$CHUNK.part"
SEGMENT="$CHUNK.segment"

if [[ $SOURCE_IS_LOCAL -eq 1 ]]; then
    printf 'Using local archive: %s (%s bytes)\n' "$CHUNK" "$MAX_BYTES"
elif [[ $SOURCE_REMOTE_FULL -eq 1 ]]; then
    if [[ -f "$CHUNK" ]]; then
        MAX_BYTES=$(file_size "$CHUNK")
        printf 'Using cached complete remote archive: %s (%s bytes)\n' \
            "$CHUNK" "$MAX_BYTES"
    else
        printf 'Downloading complete archive from %s\n' "$SOURCE_URL"
        curl --fail --location --retry 3 --retry-delay 5 \
            --retry-connrefused --progress-bar --continue-at - \
            --user-agent "chess-opening-book-builder/0.2" \
            --output "$PART" "$SOURCE_URL"
        if [[ ! -s "$PART" ]]; then
            echo "Downloaded source is empty" >&2
            exit 1
        fi
        mv "$PART" "$CHUNK"
        MAX_BYTES=$(file_size "$CHUNK")
    fi
elif [[ -f "$CHUNK" ]] && [[ $(file_size "$CHUNK") -eq $MAX_BYTES ]]; then
    printf 'Using cached %s GiB archive prefix: %s\n' "$MAX_GB" "$CHUNK"
else
    if [[ -f "$CHUNK" ]]; then
        echo "Cached file has the wrong size; refusing to overwrite it: $CHUNK" >&2
        exit 1
    fi
    CURRENT_BYTES=0
    if [[ -f "$PART" ]]; then
        CURRENT_BYTES=$(file_size "$PART")
        if [[ $CURRENT_BYTES -gt $MAX_BYTES ]]; then
            echo "Partial download is larger than requested: $PART" >&2
            exit 1
        fi
    fi

    if [[ $CURRENT_BYTES -lt $MAX_BYTES ]]; then
        rm -f "$SEGMENT"
        END_BYTE=$((MAX_BYTES - 1))
        EXPECTED_SEGMENT=$((MAX_BYTES - CURRENT_BYTES))
        printf 'Downloading bytes %s-%s from %s\n' \
            "$CURRENT_BYTES" "$END_BYTE" "$SOURCE_URL"
        HTTP_STATUS=$(curl --fail --location --retry 3 --retry-delay 5 \
            --retry-connrefused --progress-bar \
            --range "${CURRENT_BYTES}-${END_BYTE}" \
            --user-agent "chess-opening-book-builder/0.2" \
            --output "$SEGMENT" --write-out "%{http_code}" "$SOURCE_URL")
        if [[ "$HTTP_STATUS" != "206" ]] \
            || [[ $(file_size "$SEGMENT") -ne $EXPECTED_SEGMENT ]]; then
            echo "Source returned an incomplete or unexpected range response" >&2
            exit 1
        fi
        cat "$SEGMENT" >> "$PART"
        rm -f "$SEGMENT"
    fi

    if [[ $(file_size "$PART") -ne $MAX_BYTES ]]; then
        echo "Downloaded prefix does not match the requested byte count" >&2
        exit 1
    fi
    mv "$PART" "$CHUNK"
fi

if ! "${ZSTDCAT_CMD[@]}" < "$CHUNK" 2>/dev/null | head -c 1000 | grep -q "\[Event"; then
    echo "Archive prefix does not begin with valid PGN data" >&2
    exit 1
fi

decoder_end_is_expected() {
    local result="$1"
    local log="$2"
    if [[ $result -eq 0 ]]; then
        return 0
    fi
    if [[ $FULL_ARCHIVE -eq 0 ]]; then
        if [[ "$DECODER_NAME" == "python-zstandard" && $result -eq 3 ]]; then
            return 0
        fi
        if grep -Eqi 'premature end|Read error \(39\)' "$log"; then
            return 0
        fi
    fi
    return 1
}

if [[ $DOWNLOAD_ONLY -eq 1 ]]; then
    VALIDATION_LOG=$(mktemp "${TMPDIR:-/tmp}/chess-opening-book-builder-validation.XXXXXX")
    trap 'rm -f "$VALIDATION_LOG"' EXIT HUP INT TERM
    set +e
    "${ZSTDCAT_CMD[@]}" < "$CHUNK" > /dev/null 2>"$VALIDATION_LOG"
    VALIDATION_RESULT=$?
    set -e
    if ! decoder_end_is_expected "$VALIDATION_RESULT" "$VALIDATION_LOG"; then
        echo "zstd decoder failed while validating the source" >&2
        tail -5 "$VALIDATION_LOG" >&2
        exit "$VALIDATION_RESULT"
    fi
    printf 'Validated archive source: %s\n' "$CHUNK"
    exit 0
fi

RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/chess-opening-book-builder.XXXXXX")
cleanup_run_dir() {
    case "$RUN_DIR" in
        "${TMPDIR:-/tmp}"/chess-opening-book-builder.*) rm -rf "$RUN_DIR" ;;
        *) return 1 ;;
    esac
}
trap cleanup_run_dir EXIT HUP TERM
RUN_OUTPUT="$RUN_DIR/output"
mkdir "$RUN_OUTPUT"
DECODER_LOG="$RUN_DIR/zstd.log"

printf '%bBuilding rating %s, %s, ±%s Elo%b\n' \
    "$BOLD" "$RATINGS" "$SPEED_NAME" "$BAND_WIDTH" "$RESET"

set +e
INTERRUPTED=0
trap 'INTERRUPTED=1' INT
FULL_ARCHIVE_ARG=()
if [[ $FULL_ARCHIVE -eq 1 ]]; then
    FULL_ARCHIVE_ARG=(--full-archive)
fi
"${ZSTDCAT_CMD[@]}" < "$CHUNK" 2>"$DECODER_LOG" | "$PYTHON_CMD" -u "$SCRIPT_DIR/book_builder.py" \
    --ratings "$RATINGS" \
    --speeds "$SPEED_FILTER" \
    --speed-name "$SPEED_NAME" \
    --output-dir "$RUN_OUTPUT" \
    --band-width "$BAND_WIDTH" \
    --min-position-games "$MIN_POSITION_GAMES" \
    --max-plies "$MAX_PLIES" \
    --max-elo-diff "$MAX_ELO_DIFF" \
    --month "$MONTH" \
    --source-url "$SOURCE_URL" \
    --source-bytes "$MAX_BYTES" \
    --decoder "$DECODER_NAME" \
    "${FULL_ARCHIVE_ARG[@]}"
PIPE_RESULTS=("${PIPESTATUS[@]}")
trap - INT
set -e
DECODER_RESULT="${PIPE_RESULTS[0]}"
BUILDER_RESULT="${PIPE_RESULTS[1]}"

if [[ $BUILDER_RESULT -eq 130 || $INTERRUPTED -eq 1 ]]; then
    for artifact in "$RUN_OUTPUT"/*; do
        [[ -f "$artifact" ]] && mv "$artifact" "$BOOKS_DIR/"
    done
    printf '%bInterrupted: partial books saved; archive retained at %s%b\n' \
        "$YELLOW" "$CHUNK" "$RESET" >&2
    exit 130
fi

if [[ $BUILDER_RESULT -ne 0 ]]; then
    echo "Builder failed with status $BUILDER_RESULT; archive retained at $CHUNK" >&2
    exit "$BUILDER_RESULT"
fi

if ! decoder_end_is_expected "$DECODER_RESULT" "$DECODER_LOG"; then
    echo "zstd decoder failed unexpectedly; staged books were discarded" >&2
    tail -5 "$DECODER_LOG" >&2
    exit "$DECODER_RESULT"
fi

for artifact in "$RUN_OUTPUT"/*; do
    [[ -f "$artifact" ]] && mv "$artifact" "$BOOKS_DIR/"
done

if [[ $CLEAN -eq 1 && $SOURCE_IS_LOCAL -eq 0 ]]; then
    rm -f "$CHUNK"
    printf 'Removed cached archive prefix.\n'
else
    if [[ $SOURCE_IS_LOCAL -eq 1 ]]; then
        printf 'Local source was not modified: %s\n' "$CHUNK"
    else
        printf 'Retained cached archive prefix: %s\n' "$CHUNK"
    fi
fi
printf '%bBooks built in %s%b\n' "$GREEN" "$BOOKS_DIR" "$RESET"
