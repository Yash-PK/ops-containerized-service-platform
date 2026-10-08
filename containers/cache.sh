#!/bin/sh
set -eu
umask 077
password=$(cat /run/secrets/cache_password)
case "$password" in *[!a-f0-9]* | '') exit 2 ;; esac
[ "${#password}" -eq 48 ] || exit 2
cat >/tmp/valkey.conf <<CONFIG
bind 0.0.0.0
protected-mode yes
port 6379
requirepass $password
save ""
appendonly no
maxmemory 32mb
maxmemory-policy allkeys-lru
logfile ""
CONFIG
unset password
exec valkey-server /tmp/valkey.conf
