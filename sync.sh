#!/bin/sh
set -eu
cd "$(dirname "$0")"
GIT_SSH_COMMAND='ssh -i /var/oled/data/monkeykingonline/.github/deploy_key -o IdentitiesOnly=yes' git pull --rebase
GIT_SSH_COMMAND='ssh -i /var/oled/data/monkeykingonline/.github/deploy_key -o IdentitiesOnly=yes' git push
