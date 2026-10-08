#!/bin/sh
set -eu
VALKEYCLI_AUTH=$(cat /run/secrets/cache_password)
export VALKEYCLI_AUTH
[ "$(valkey-cli --no-auth-warning ping)" = PONG ]
