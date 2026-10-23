#!/bin/sh
# Segment firewall rules for the lab.
#
# Model: default-deny between segments. Only the explicitly listed
# segment-to-segment TCP flows are allowed. Replies to allowed flows are
# accepted via connection tracking (ESTABLISHED,RELATED).
#
# Segments (see docs/topology.md):
#   user        10.10.10.0/24
#   server      10.10.20.0/24
#   management  10.10.30.0/24
#   industrial  10.10.40.0/24
set -eu

USER_NET=10.10.10.0/24
SERVER_NET=10.10.20.0/24
MGMT_NET=10.10.30.0/24
INDUSTRIAL_NET=10.10.40.0/24

# Start from a clean slate so re-running the script is idempotent.
iptables -F
iptables -X

# Default policies: drop everything not explicitly allowed.
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# The router itself: loopback and replies only (no management services exposed).
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# Forwarded traffic: replies to allowed flows.
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# allow SRC DST PORT: forward new TCP connections from SRC subnet to DST subnet on PORT.
allow() {
    iptables -A FORWARD -s "$1" -d "$2" -p tcp --dport "$3" -m conntrack --ctstate NEW -j ACCEPT
}

allow "$USER_NET"       "$SERVER_NET"     8080   # user -> app web service
allow "$MGMT_NET"       "$SERVER_NET"     8080   # engineering -> app web service
allow "$SERVER_NET"     "$INDUSTRIAL_NET" 502    # server historian -> PLC (Modbus/TCP)
allow "$MGMT_NET"       "$INDUSTRIAL_NET" 502    # engineering -> PLC (Modbus/TCP)

# Everything else (user->management, user->industrial, server->management,
# any traffic initiated from industrial) is dropped by the FORWARD policy.
echo "segment rules applied"
iptables -S FORWARD
