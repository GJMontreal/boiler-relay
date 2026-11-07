#!/bin/sh
INSTALL_DIR="/home/heating/boiler_relay"

cd $INSTALL_DIR

python3 -m venv ./.venv
. ./.venv/bin/activate
python3 -m pip install -r requirements.txt
