#!/bin/bash
set -e

REMOTE_USER=$1
REMOTE_HOST=$2

if [ -z "${REMOTE_USER}" ] || [ -z "${REMOTE_HOST}" ]; then
    echo "usage: ./deploy.sh <user> <host>"
    exit 1
fi

PROJECT_NAME=boiler_relay
SERVICE_USER="${SERVICE_USER:-heating}"
INSTALL_DIR="/var/lib/${PROJECT_NAME}"

TEMPLATES=(
    "deploy/setup_python.sh.template"
    "deploy/boiler_relay.service.template"
)

echo "Creating files from templates"
for INPUT_FILE in "${TEMPLATES[@]}"; do
    OUTPUT_FILE=${INPUT_FILE%.*}
    sed -e "s/<project_name>/${PROJECT_NAME}/g" -e "s/<service_user>/${SERVICE_USER}/g" "${INPUT_FILE}" > "${OUTPUT_FILE}"
done

chmod +x deploy/setup_python.sh

SSH_CMD="ssh ${REMOTE_USER}@${REMOTE_HOST}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

${SSH_CMD} sudo rm -rf "${INSTALL_DIR}"
${SSH_CMD} sudo mkdir -p "${INSTALL_DIR}"
${SSH_CMD} sudo chown "${REMOTE_USER}" "${INSTALL_DIR}"
for DIR in boiler_relay boiler_relay/outputs config deploy; do
    echo creating dir "${INSTALL_DIR}/${DIR}"
    ${SSH_CMD} mkdir "${INSTALL_DIR}/${DIR}"
done

echo copying files
scp requirements.txt "${REMOTE}:${INSTALL_DIR}/"
scp boiler_relay/*.py "${REMOTE}:${INSTALL_DIR}/boiler_relay/"
scp boiler_relay/outputs/*.py "${REMOTE}:${INSTALL_DIR}/boiler_relay/outputs/"
scp config/system_config.json "${REMOTE}:${INSTALL_DIR}/config/"
scp deploy/setup_python.sh deploy/boiler_relay.service "${REMOTE}:${INSTALL_DIR}/deploy/"

echo creating venv
${SSH_CMD} "${INSTALL_DIR}/deploy/setup_python.sh"

echo "to install the service run on the device:"
echo "sudo cp ${INSTALL_DIR}/deploy/boiler_relay.service /etc/systemd/system && sudo systemctl daemon-reload && sudo systemctl enable --now boiler_relay"
