FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /job
RUN pip install --no-cache-dir prometheus-client==0.26.0
COPY daily_report.py .

CMD ["python", "daily_report.py"]
