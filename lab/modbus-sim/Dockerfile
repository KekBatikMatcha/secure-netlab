# Simulated Modbus/TCP PLC on the industrial segment. Standard library only.
FROM python:3.12-alpine3.20

COPY modbus_server.py /opt/modbus/modbus_server.py

EXPOSE 502
CMD ["python", "/opt/modbus/modbus_server.py", "--port", "502"]
