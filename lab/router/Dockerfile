# Segment router/firewall: forwards between the four lab networks and applies iptables rules.
FROM alpine:3.20

RUN apk add --no-cache iptables

COPY rules.sh /usr/local/bin/rules.sh

# Apply the firewall rules, then keep the container alive.
CMD ["sh", "-c", "sh /usr/local/bin/rules.sh && exec tail -f /dev/null"]
