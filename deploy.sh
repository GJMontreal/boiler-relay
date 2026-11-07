#!/bin/bash

# we're ok with this failing, particularly the ssh commands to stop and start services

#make sure to install ssh keys using ssh-key-id
# ssh-key-id -i <key.pub> user@host

#usage ./deploy.sh <USER> <HOST>
#these should be environment variables or command line arguments
REMOTE_USER=$1
REMOTE_HOST=$2

#ensure that INSTALL_DIR matches what is in the unit files
PROJECT_NAME=boiler_relay
INSTALL_DIR="/home/${REMOTE_USER}/${PROJECT_NAME}"

#change any paths in the scripts and unit files to reflect this user
#we don't use the -i option to keep it working across platforms
TEMPLATES=(\
          "deploy/setup_python.sh.template"
          "deploy/boiler_relay.service.template"
          )

echo "Creating files from templates"
for INPUT_FILE in ${TEMPLATES[*]}; do
    OUTPUT_FILE=${INPUT_FILE%.*}
    sed "s/<user_name>/$REMOTE_USER/g" "${INPUT_FILE}" > "temp.template"
    sed "s/<project_name>/$PROJECT_NAME/g" "temp.template" > "${OUTPUT_FILE}"
done

rm temp.template

chmod +x "deploy/setup_python.sh"

WORKING_DIR=`pwd`
echo $WORKING_DIR
FILES_TO_COPY=(\
                "requirements.txt" \
                "deploy/setup_python.sh" \
                "deploy/boiler_relay.service" \
                "config/system_config.json" \
                "boiler_relay/*.py" \
                "boiler_relay/outputs/*.py"
                )

REMOTE_DIRS=(\
            "boiler_relay"\
            "boiler_relay/outputs"\
            "config"\
            "deploy"
            )

SSH_CMD="ssh ${REMOTE_USER}@${REMOTE_HOST}"

# !DANGER WILL ROBINSON DANGER!
${SSH_CMD} rm -rf $INSTALL_DIR
${SSH_CMD} mkdir "${INSTALL_DIR}"
for DIR in ${REMOTE_DIRS[*]}; do
    echo creating dir "${INSTALL_DIR}/${DIR}"
    ${SSH_CMD} mkdir "${INSTALL_DIR}/${DIR}"
done

echo copying files
for FILE in ${FILES_TO_COPY[*]}; do
    LOCAL_PATH="${WORKING_DIR}/${FILE}"
    REMOTE_PATH="${INSTALL_DIR}/${FILE}"
    eval "scp ${LOCAL_PATH} ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}"
done

echo creating venv
${SSH_CMD} "${INSTALL_DIR}/deploy/setup_python.sh"

echo installing services

# ${SSH_CMD} sudo cp "${INSTALL_DIR}/deploy/boiler_relay.service" /etc/systemd/system
