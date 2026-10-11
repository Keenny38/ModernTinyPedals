#!/bin/sh
set -eu

CONFIG_BASE="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_FILE="${CONFIG_BASE}/NeoPedal/launcher.conf"
# Older versions: folder copied by the app on first start, launcher may run before
if [ ! -f "${CONFIG_FILE}" ];
then
    CONFIG_FILE="${CONFIG_BASE}/TinyPedal/launcher.conf"
fi
if [ -f "${CONFIG_FILE}" ] && [ -z "${TINYPEDAL_RUN_ARGS:-}" ];
then
    . "${CONFIG_FILE}"
fi

./run.py ${TINYPEDAL_RUN_ARGS:-} "$@"
