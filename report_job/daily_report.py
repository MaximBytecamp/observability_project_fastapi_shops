"""Ночной отчёт: короткая задача, которая считает выручку за день и завершается.

Почему push, а не pull: задача живёт несколько секунд. Prometheus опрашивает
цели раз в 15 секунд и, скорее всего, ни разу не застанет её запущенной —
к моменту scrape процесса уже нет, и его /metrics некому отдать.
Поэтому перед завершением задача сама отправляет (push) свои метрики
в Pushgateway. Pushgateway работает постоянно и хранит последнее
отправленное значение, а Prometheus забирает его оттуда обычным pull.

Число заказов здесь СЛУЧАЙНОЕ: у задачи нет доступа к памяти API
(базы данных в проекте нет). Важен механизм отправки, а не цифра.
"""

import os
import random
import time

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

PUSHGATEWAY = os.getenv("PUSHGATEWAY_URL", "pushgateway:9091")


def main() -> None:
    started = time.time()

    # Отдельный реестр только для этой задачи: в Pushgateway уйдут ровно три метрики.
    registry = CollectorRegistry()
    last_success = Gauge(
        "coffee_daily_report_last_success_timestamp_seconds",
        "Время последнего успешного завершения ночного отчёта (Unix time)",
        registry=registry,
    )
    duration = Gauge(
        "coffee_daily_report_duration_seconds",
        "Сколько длился последний ночной отчёт",
        registry=registry,
    )
    orders = Gauge(
        "coffee_daily_report_orders",
        "Сколько заказов посчитано в последнем отчёте (учебное случайное значение)",
        registry=registry,
    )

    print("daily_report: считаю выручку за день...", flush=True)
    time.sleep(random.uniform(2, 5))  # «работа»
    orders_count = random.randint(150, 400)
    print(f"daily_report: заказов за день {orders_count}", flush=True)

    orders.set(orders_count)
    duration.set(time.time() - started)
    # Время успеха ставим ПОСЛЕДНИМ: если задача упадёт раньше, метрика
    # останется со старым значением, и по возрасту (time() - метрика)
    # будет видно, что отчёт давно не проходил.
    last_success.set_to_current_time()

    # job="daily_report", метку instance не задаём: у короткой задачи нет
    # постоянного адреса, а случайный instance (имя контейнера) при каждом
    # запуске создавал бы в Pushgateway новую группу, и старые бы копились.
    push_to_gateway(PUSHGATEWAY, job="daily_report", registry=registry)
    print(f"daily_report: метрики отправлены в {PUSHGATEWAY}", flush=True)


if __name__ == "__main__":
    main()
