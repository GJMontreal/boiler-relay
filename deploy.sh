#!/bin/bash
set -e

REMOTE_USER=$1
REMOTE_HOST=$2

if [ -z "${REMOTE_USER}" ] || [ -z "${REMOTE_HOST}" ]; then
    echo "usage: ./deploy.sh <user> <host>"
    exit 1
fi

SERVICE_NAME=boiler_relay_v2
SERVICE_USER="${SERVICE_USER:-heating}"
INSTALL_DIR="/var/lib/${SERVICE_NAME}"
LEGACY_DIRS=(/var/lib/boiler_relay /home/debian/boiler-relay)

for LEGACY_DIR in "${LEGACY_DIRS[@]}"; do
    if [ "${INSTALL_DIR%/}" = "${LEGACY_DIR}" ]; then
        echo "refusing to deploy to the legacy directory ${LEGACY_DIR}"
        exit 1
    fi
done

TEMPLATES=(
    "deploy/setup_python.sh.template"
    "deploy/${SERVICE_NAME}.service.template"
    "deploy/${SERVICE_NAME}_shadow.service.template"
)

echo "Creating files from templates"
for INPUT_FILE in "${TEMPLATES[@]}"; do
    OUTPUT_FILE=${INPUT_FILE%.*}
    sed -e "s/<service_name>/${SERVICE_NAME}/g" -e "s/<service_user>/${SERVICE_USER}/g" "${INPUT_FILE}" > "${OUTPUT_FILE}"
done

STAGE=$(mktemp -d)
trap 'rm -rf "${STAGE}"' EXIT

mkdir -p "${STAGE}/boiler_relay/outputs" "${STAGE}/config" "${STAGE}/deploy"
cp requirements.txt "${STAGE}/"
cp boiler_relay/*.py "${STAGE}/boiler_relay/"
cp boiler_relay/outputs/*.py "${STAGE}/boiler_relay/outputs/"
cp config/system_config.json "${STAGE}/config/"
cp deploy/setup_python.sh "deploy/${SERVICE_NAME}.service" "deploy/${SERVICE_NAME}_shadow.service" "${STAGE}/deploy/"
cp -R deploy/boiler_relay.service.d "${STAGE}/deploy/"

VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' boiler_relay/version.py)
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
if [ "${COMMIT}" != unknown ] && [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    COMMIT="${COMMIT}-dirty"
fi
printf '{"version": "%s", "commit": "%s"}\n' "${VERSION}" "${COMMIT}" > "${STAGE}/build_info.json"
chmod -R u=rwX,go=rX "${STAGE}"

SSH_CMD="ssh ${REMOTE_USER}@${REMOTE_HOST}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

${SSH_CMD} sudo mkdir -p "${INSTALL_DIR}"
${SSH_CMD} sudo chown "${REMOTE_USER}" "${INSTALL_DIR}"

echo copying files
rsync -rltp --delete --exclude=/.venv "${STAGE}/" "${REMOTE}:${INSTALL_DIR}/"

echo creating venv
${SSH_CMD} sh "${INSTALL_DIR}/deploy/setup_python.sh"

echo "to install the units and the legacy drop-in run on the device:"
echo "sudo cp ${INSTALL_DIR}/deploy/*.service /etc/systemd/system/ && sudo mkdir -p /etc/systemd/system/boiler_relay.service.d && sudo cp ${INSTALL_DIR}/deploy/boiler_relay.service.d/conflicts.conf /etc/systemd/system/boiler_relay.service.d/ && sudo systemctl daemon-reload"
echo "to start the shadow at boot, without starting ${SERVICE_NAME}, run on the device:"
echo "sudo systemctl enable ${SERVICE_NAME}_shadow"
echo "then run deploy/switch.sh ${REMOTE_USER} ${REMOTE_HOST} legacy|v2|shadow"
