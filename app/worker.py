"""Фоновый обработчик очереди: бариста.

Каждый бариста — отдельная asyncio-задача внутри процесса API. Она берёт заказ
из очереди, «готовит» его (asyncio.sleep) и записывает результат.

Хранение — в памяти процесса: словарь ORDERS_DB и asyncio.Queue.
После перезапуска контейнера заказы теряются. Это осознанное упрощение:
нас интересует мониторинг, а не надёжное хранение.
"""

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass

from metrics import BARISTAS_BUSY, ORDER_PREPARE, ORDERS, QUEUE_LENGTH

log = logging.getLogger("coffee.worker")

# Среднее время приготовления, секунды.
PREPARE_TIME = {
    "espresso": 1.0,
    "americano": 1.5,
    "latte": 2.5,
    "cappuccino": 2.5,
    "raf": 4.0,
}
MENU = list(PREPARE_TIME)

SPREAD = 0.30          # случайный разброс ±30 %
FAIL_RATE = 0.03       # ~3 % заказов — «сломалась кофемашина»
QUEUE_LIMIT = 50       # больше 50 заказов в очереди — отвечаем 503

# Опыт: SLOW_MODE=1 — всё готовится в 3 раза дольше.
SLOW_FACTOR = 3.0 if os.getenv("SLOW_MODE", "0") == "1" else 1.0

# Число бариста. 6 обработчиков при среднем времени ~2,3 с успевают
# примерно 2,6 заказа в секунду: сценарий normal (2 заказа/с) проходит
# без переполнения, а rush (10 заказов/с) быстро заполняет очередь.
BARISTAS = int(os.getenv("BARISTAS", "6"))


@dataclass
class Order:
    id: int
    drink: str
    size: str
    status: str = "queued"  # queued → preparing → ready | failed


ORDERS_DB: dict[int, Order] = {}
queue: asyncio.Queue[Order] = asyncio.Queue()


def update_queue_gauge() -> None:
    # gauge ставим в текущее значение, а не делаем inc/dec вручную:
    # так значение не «уплывёт», даже если где-то забудем парный вызов.
    QUEUE_LENGTH.set(queue.qsize())


def prepare_duration(drink: str) -> float:
    base = PREPARE_TIME[drink] * SLOW_FACTOR
    return base * random.uniform(1 - SPREAD, 1 + SPREAD)


async def barista(number: int) -> None:
    while True:
        order = await queue.get()
        update_queue_gauge()

        order.status = "preparing"
        BARISTAS_BUSY.inc()
        started = time.perf_counter()
        try:
            await asyncio.sleep(prepare_duration(order.drink))

            if random.random() < FAIL_RATE:
                order.status = "failed"
                ORDERS.labels(drink=order.drink, result="failed").inc()
                # Номер заказа — в логе (уровень ERROR), но не в метке метрики.
                log.error(
                    "order_failed: сломалась кофемашина",
                    extra={"order_id": order.id, "drink": order.drink},
                )
            else:
                order.status = "ready"
                ORDERS.labels(drink=order.drink, result="ready").inc()
                # В гистограмму попадают только приготовленные напитки:
                # время до поломки — это не «время приготовления».
                ORDER_PREPARE.labels(drink=order.drink).observe(
                    time.perf_counter() - started
                )
        finally:
            # finally: даже при ошибке бариста освобождается, gauge не «залипнет».
            BARISTAS_BUSY.dec()
            queue.task_done()


def start_baristas() -> list[asyncio.Task]:
    log.info(f"baristas_started: {BARISTAS}, slow_factor={SLOW_FACTOR}")
    return [asyncio.create_task(barista(i)) for i in range(BARISTAS)]
