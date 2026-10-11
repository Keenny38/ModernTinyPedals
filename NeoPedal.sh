#!/bin/sh
set -eu

CONFIG_BASE="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_FILE="${CONFIG_BASE}/NeoPedal/launcher.conf"
if [ -f "${CONFIG_FILE}" ] && [ -z "${NEOPEDAL_RUN_ARGS:-}" ];
then
    . "${CONFIG_FILE}"
fi

./run.py ${NEOPEDAL_RUN_ARGS:-} "$@"
