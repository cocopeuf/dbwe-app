#!/bin/bash

set -e

if [ ! -d "migrations" ]; then
    flask db init
fi

flask db migrate || true
flask db upgrade || true

exec "$@"
