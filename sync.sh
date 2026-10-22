#!/bin/sh
set -eu
cd "$(dirname "$0")"
git pull --rebase
git push
