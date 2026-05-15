#!/usr/bin/env bash
# Bootstrap a local virtual environment and install the app's dependencies.
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"
PYTHON_BIN="${PYTHON:-python3}"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR (using $PYTHON_BIN)..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo
echo "Done. Activate the environment with:"
echo "    source $VENV_DIR/bin/activate"
echo "Then run the app with:"
echo "    python app.py"
echo "Or use the helper:"
echo "    ./run.sh"
