#!/bin/sh
set -eu

CONFIG_BASE="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_FILE="${CONFIG_BASE}/NeoPedal/launcher.conf"
# Older versions: folder copied by the app on first start, launcher may run before
if [ ! -f "${CONFIG_FILE}" ];
then
    CONFIG_FILE="${CONFIG_BASE}/TinyPedal/launcher.conf"
fi
if [ -f "${CONFIG_FILE}" ] && [ -z "${NEOPEDAL_RUN_ARGS:-}" ];
then
    . "${CONFIG_FILE}"
    # Variable named TINYPEDAL_RUN_ARGS until 0.23.0
    NEOPEDAL_RUN_ARGS="${NEOPEDAL_RUN_ARGS:-${TINYPEDAL_RUN_ARGS:-}}"
fi

./run.py ${NEOPEDAL_RUN_ARGS:-} "$@"
