#!/usr/bin/env bash
# Run the Flask app using the project's virtualenv.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "No .venv found. Run ./setup.sh first." >&2
    exit 1
fi

exec .venv/bin/python app.py "$@"
