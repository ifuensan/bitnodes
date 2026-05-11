#!/usr/bin/env bash
# start_pcap.sh - sniffer pasivo para alimentar cache_inv.py
set -euo pipefail

IFACE="enp33s0"
PCAP_DIR="/mnt/datos/home_data/Work/myprojects/research/bitnodes/data/pcap/f9beb4d9"
USER_DROP="ifuensan"
LOG="/tmp/tcpdump-f9beb4d9.log"

if pgrep -f "tcpdump.*${PCAP_DIR}" >/dev/null; then
    echo "tcpdump ya está corriendo:"
    pgrep -af tcpdump | grep "${PCAP_DIR}"
    exit 0
fi

mkdir -p "${PCAP_DIR}"
sudo -v
nohup sudo tcpdump -i "${IFACE}" -nn -s 0 -G 30 -W 4 \
    -Z "${USER_DROP}" \
    -w "${PCAP_DIR}/%s.pcap" \
    'tcp and tcp[((tcp[12]&0xf0)>>2):4] = 0xf9beb4d9' \
    > "${LOG}" 2>&1 &
disown
echo "tcpdump arrancado, log: ${LOG}"
