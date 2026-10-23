FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

EXPOSE 8000

# Один процесс uvicorn: заказы и метрики хранятся в памяти процесса.
# При нескольких процессах каждый отдавал бы на /metrics свои числа.
# --no-access-log: запись о запросе пишет наш middleware в JSON.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
