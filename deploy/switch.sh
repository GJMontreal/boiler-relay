#!/bin/bash
set -e

REMOTE_USER=$1
REMOTE_HOST=$2
TARGET=$3

if [ -z "${REMOTE_USER}" ] || [ -z "${REMOTE_HOST}" ]; then
    echo "usage: deploy/switch.sh <user> <host> legacy|v2|shadow"
    exit 1
fi

LEGACY=boiler_relay
V2=boiler_relay_v2
SHADOW=boiler_relay_v2_shadow
WAIT_SECONDS=30

case "${TARGET}" in
    legacy) STOP=("${V2}" "${SHADOW}"); START=("${LEGACY}"); ENABLE=${LEGACY}; DISABLE=${V2} ;;
    v2) STOP=("${LEGACY}" "${SHADOW}"); START=("${V2}"); ENABLE=${V2}; DISABLE=${LEGACY} ;;
    shadow) STOP=("${V2}"); START=("${LEGACY}" "${SHADOW}"); ENABLE=${LEGACY}; DISABLE=${V2} ;;
    *)
        echo "usage: deploy/switch.sh <user> <host> legacy|v2|shadow"
        exit 1
        ;;
esac

REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

unit_exists() { ssh "${REMOTE}" systemctl cat "$1.service" > /dev/null 2>&1; }
unit_active() { ssh "${REMOTE}" systemctl is-active --quiet "$1.service"; }
sctl() { ssh -t "${REMOTE}" sudo systemctl "$@"; }

wait_inactive() {
    for _ in $(seq "${WAIT_SECONDS}"); do
        unit_active "$1" || return 0
        sleep 1
    done
    echo "$1 is still active after ${WAIT_SECONDS} seconds"
    exit 1
}

for UNIT in "${START[@]}"; do
    if ! unit_exists "${UNIT}"; then
        echo "${UNIT}.service is not installed on the device, nothing was changed"
        exit 1
    fi
done

for UNIT in "${STOP[@]}"; do
    if unit_exists "${UNIT}"; then
        sctl stop "${UNIT}"
        wait_inactive "${UNIT}"
    fi
done

for UNIT in "${START[@]}"; do
    sctl start "${UNIT}"
done

sleep 3
for UNIT in "${START[@]}"; do
    if ! unit_active "${UNIT}"; then
        echo "${UNIT} did not stay up, boot-time enables are unchanged"
        exit 1
    fi
done

sctl enable "${ENABLE}"
if unit_exists "${DISABLE}"; then
    sctl disable "${DISABLE}"
fi
