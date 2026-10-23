# Monitor service. Build context is the repo root so the image can include the automation package
# (the state schema lives there).
FROM python:3.12-alpine3.20

WORKDIR /app
COPY monitor/requirements.txt /app/monitor/requirements.txt
RUN pip install --no-cache-dir -r /app/monitor/requirements.txt

COPY automation /app/automation
COPY monitor /app/monitor

ENV PYTHONUNBUFFERED=1
EXPOSE 9101
CMD ["python", "-m", "monitor.app", "--targets", "/app/monitor/targets.yaml", "--state", "/state/state.json"]
