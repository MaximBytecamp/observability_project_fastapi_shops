"""Логи в JSON: одна запись — одна строка в стандартный вывод.

Почему JSON: запись читает не только человек, но и программа (Loki, Elasticsearch,
jq). У каждой записи одинаковые поля, по ним можно искать и фильтровать.

Лог отвечает на вопрос «что случилось с ЭТИМ запросом / ЭТИМ заказом»,
поэтому в нём есть request_id и номер заказа. Метрика отвечает на вопрос
«сколько и как быстро в целом», поэтому в её метках этих полей нет.
"""

import json
import logging
import sys
from datetime import datetime, timezone

SERVICE_NAME = "coffee-api"

# Поля, которые можно передать через logger.info(..., extra={...}).
EXTRA_FIELDS = (
    "method",
    "route",
    "status",
    "duration_ms",
    "request_id",
    "order_id",
    "drink",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            # Время в UTC в формате ISO 8601: одинаково читается в любой зоне.
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": SERVICE_NAME,
            "event": record.getMessage(),
        }
        for field in EXTRA_FIELDS:
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # Собственные записи uvicorn (запуск, остановка) тоже переводим в JSON,
    # чтобы в выводе контейнера не было строк другого формата.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # Журнал доступа uvicorn отключаем: запись о каждом запросе пишет наш middleware,
    # иначе на один запрос было бы две записи.
    logging.getLogger("uvicorn.access").disabled = True

    return logging.getLogger("coffee")
