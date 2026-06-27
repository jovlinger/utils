#!/bin/sh
# Read dmz.conf and write generated install/ artifacts for build-and-write.sh.
# Usage: parse-dmz-conf.sh CONF_FILE OUT_DIR

set -eu

_conf="${1:?conf file}"
_out="${2:?output directory}"

if [ ! -f "$_conf" ]; then
	echo "parse-dmz-conf.sh: missing $_conf" >&2
	exit 1
fi
mkdir -p "$_out"

NETWORK_ADDR="10.1.1.2/24"
NETWORK_GATEWAY="10.1.1.1"
DNS_SERVERS="1.1.1.1,8.8.8.8,8.8.4.4"
SSHD_ON_BOOT="no"
PORT="5000"
UI_PORT="8090"
THERMO_UI_PUBLIC_ORIGIN=""
DMZ_PUBLIC_BASE_URL=""
OAUTH_SESSION_LIFETIME_SECS="2592000"
LONG_POLL_TIMEOUT_SECS="60"
LONG_POLL_SLEEP_SECS="1.0"
LOG_LEVEL="INFO"
OBSOLETE_LOG_SUPPRESS_REPEAT="10"

_read_conf() {
	_line="$1"
	_line=$(printf '%s' "$_line" | sed 's/[[:space:]]*#.*//' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
	[ -n "$_line" ] || return 0
	case "$_line" in
	*=*) ;;
	*)
		echo "parse-dmz-conf.sh: invalid line (expected KEY=VALUE): $_line" >&2
		exit 1
		;;
	esac
	_key="${_line%%=*}"
	_val="${_line#*=}"
	case "$_key" in
	NETWORK_ADDR) NETWORK_ADDR="$_val" ;;
	NETWORK_GATEWAY) NETWORK_GATEWAY="$_val" ;;
	DNS_SERVERS) DNS_SERVERS="$_val" ;;
	SSHD_ON_BOOT) SSHD_ON_BOOT="$_val" ;;
	PORT) PORT="$_val" ;;
	UI_PORT) UI_PORT="$_val" ;;
	THERMO_UI_PUBLIC_ORIGIN) THERMO_UI_PUBLIC_ORIGIN="$_val" ;;
	DMZ_PUBLIC_BASE_URL) DMZ_PUBLIC_BASE_URL="$_val" ;;
	OAUTH_SESSION_LIFETIME_SECS) OAUTH_SESSION_LIFETIME_SECS="$_val" ;;
	LONG_POLL_TIMEOUT_SECS) LONG_POLL_TIMEOUT_SECS="$_val" ;;
	LONG_POLL_SLEEP_SECS) LONG_POLL_SLEEP_SECS="$_val" ;;
	LOG_LEVEL) LOG_LEVEL="$_val" ;;
	OBSOLETE_LOG_SUPPRESS_REPEAT) OBSOLETE_LOG_SUPPRESS_REPEAT="$_val" ;;
	*)
		echo "parse-dmz-conf.sh: unknown key $_key" >&2
		exit 1
		;;
	esac
}

_check_port() {
	_name="$1"
	_val="$2"
	case "$_val" in
	'' | *[!0-9]*)
		echo "parse-dmz-conf.sh: $_name must be a port number 1-65535 (got $_val)" >&2
		exit 1
		;;
	esac
	if [ "$_val" -lt 1 ] 2>/dev/null || [ "$_val" -gt 65535 ] 2>/dev/null; then
		echo "parse-dmz-conf.sh: $_name must be 1-65535 (got $_val)" >&2
		exit 1
	fi
}

_check_optional_url() {
	_name="$1"
	_val="$2"
	[ -z "$_val" ] && return 0
	case "$_val" in
	http://* | https://*) ;;
	*)
		echo "parse-dmz-conf.sh: $_name must be empty or start with http:// or https:// (got $_val)" >&2
		exit 1
		;;
	esac
}

while IFS= read -r _raw || [ -n "$_raw" ]; do
	_read_conf "$_raw"
done <"$_conf"

case "$NETWORK_ADDR" in
*/*) ;;
*)
	echo "parse-dmz-conf.sh: NETWORK_ADDR must be ADDR/CIDR (got $NETWORK_ADDR)" >&2
	exit 1
	;;
esac
case "$NETWORK_GATEWAY" in
*.*.*.*) ;;
*)
	echo "parse-dmz-conf.sh: NETWORK_GATEWAY must be an IPv4 address (got $NETWORK_GATEWAY)" >&2
	exit 1
	;;
esac

_check_port PORT "$PORT"
_check_port UI_PORT "$UI_PORT"
_check_optional_url THERMO_UI_PUBLIC_ORIGIN "$THERMO_UI_PUBLIC_ORIGIN"
_check_optional_url DMZ_PUBLIC_BASE_URL "$DMZ_PUBLIC_BASE_URL"

_sshd_norm=$(printf '%s' "$SSHD_ON_BOOT" | tr '[:upper:]' '[:lower:]')
case "$_sshd_norm" in
yes | true | 1 | on) SSHD_ON_BOOT_OUT=yes ;;
no | false | 0 | off | "") SSHD_ON_BOOT_OUT=no ;;
*)
	echo "parse-dmz-conf.sh: SSHD_ON_BOOT must be yes/no (got $SSHD_ON_BOOT)" >&2
	exit 1
	;;
esac

_log_norm=$(printf '%s' "$LOG_LEVEL" | tr '[:lower:]' '[:upper:]')
case "$_log_norm" in
TRACE | DEBUG | INFO | WARNING | ERROR) LOG_LEVEL="$_log_norm" ;;
	*)
	echo "parse-dmz-conf.sh: LOG_LEVEL must be TRACE, DEBUG, INFO, WARNING, or ERROR (got $LOG_LEVEL)" >&2
	exit 1
	;;
esac

case "$OBSOLETE_LOG_SUPPRESS_REPEAT" in
'' | *[!0-9]*)
	echo "parse-dmz-conf.sh: OBSOLETE_LOG_SUPPRESS_REPEAT must be a non-negative integer (got $OBSOLETE_LOG_SUPPRESS_REPEAT)" >&2
	exit 1
	;;
esac

case "$OAUTH_SESSION_LIFETIME_SECS" in
'' | *[!0-9]*)
	echo "parse-dmz-conf.sh: OAUTH_SESSION_LIFETIME_SECS must be a non-negative integer (got $OAUTH_SESSION_LIFETIME_SECS)" >&2
	exit 1
	;;
esac

case "$LONG_POLL_TIMEOUT_SECS" in
'' | *[!0-9.]*)
	echo "parse-dmz-conf.sh: LONG_POLL_TIMEOUT_SECS must be a number (got $LONG_POLL_TIMEOUT_SECS)" >&2
	exit 1
	;;
esac
case "$LONG_POLL_SLEEP_SECS" in
'' | *[!0-9.]*)
	echo "parse-dmz-conf.sh: LONG_POLL_SLEEP_SECS must be a number (got $LONG_POLL_SLEEP_SECS)" >&2
	exit 1
	;;
esac

: >"$_out/dns.conf"
_dns_remain="$DNS_SERVERS"
while [ -n "$_dns_remain" ]; do
	case "$_dns_remain" in
	*,*)
		_ns="${_dns_remain%%,*}"
		_dns_remain="${_dns_remain#*,}"
		;;
	*)
		_ns="$_dns_remain"
		_dns_remain=""
		;;
	esac
	_ns=$(printf '%s' "$_ns" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
	[ -z "$_ns" ] && continue
	case "$_ns" in
	*.*.*.*) ;;
	*)
		echo "parse-dmz-conf.sh: DNS_SERVERS entry must be IPv4 (got $_ns)" >&2
		exit 1
		;;
	esac
	printf '%s\n' "$_ns" >>"$_out/dns.conf"
done
if [ ! -s "$_out/dns.conf" ]; then
	echo "parse-dmz-conf.sh: DNS_SERVERS must list at least one resolver" >&2
	exit 1
fi

printf '%s %s\n' "$NETWORK_ADDR" "$NETWORK_GATEWAY" >"$_out/network.conf"
printf '%s\n' "$SSHD_ON_BOOT_OUT" >"$_out/sshd-on-boot"
{
	printf 'PORT=%s\n' "$PORT"
	printf 'UI_PORT=%s\n' "$UI_PORT"
	printf 'OAUTH_SESSION_LIFETIME_SECS=%s\n' "$OAUTH_SESSION_LIFETIME_SECS"
	printf 'LONG_POLL_TIMEOUT_SECS=%s\n' "$LONG_POLL_TIMEOUT_SECS"
	printf 'LONG_POLL_SLEEP_SECS=%s\n' "$LONG_POLL_SLEEP_SECS"
	printf 'LOG_LEVEL=%s\n' "$LOG_LEVEL"
	printf 'OBSOLETE_LOG_SUPPRESS_REPEAT=%s\n' "$OBSOLETE_LOG_SUPPRESS_REPEAT"
	if [ -n "$THERMO_UI_PUBLIC_ORIGIN" ]; then
		printf 'THERMO_UI_PUBLIC_ORIGIN=%s\n' "$THERMO_UI_PUBLIC_ORIGIN"
	fi
	if [ -n "$DMZ_PUBLIC_BASE_URL" ]; then
		printf 'DMZ_PUBLIC_BASE_URL=%s\n' "$DMZ_PUBLIC_BASE_URL"
	fi
} >"$_out/dmz-app.env"
