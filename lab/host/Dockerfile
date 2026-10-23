# Generic simulated endpoint (user PC, app server, engineering workstation).
# Each service sets its own default route and listener via compose `command`.
FROM python:3.12-alpine3.20

COPY tools/ /opt/tools/
RUN mkdir -p /srv/www && echo "secure-netlab endpoint" > /srv/www/index.html

WORKDIR /opt/tools
