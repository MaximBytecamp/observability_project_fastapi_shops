"""API кофейни: приём заказов, статус, меню и страница /metrics."""

import asyncio
import itertools
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from logging_setup import setup_logging
from metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS, ORDERS_REJECTED, registry
import worker

log = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = worker.start_baristas()
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Кофейня", lifespan=lifespan)

# Служебные адреса не учитываем в HTTP-метриках: их опрашивают Prometheus
# и проверки живости, а не клиенты. Иначе каждые 15 секунд счётчик рос бы сам
# по себе, и «запросов в секунду» никогда не было бы ноль.
NOT_COUNTED = {"/metrics", "/metrics/slow", "/health"}

order_ids = itertools.count(1)


# ------------------------------------------------------------------ middleware


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    """Один «турникет» для всех запросов: метрики и запись в лог.

    Счётчик увеличивается здесь, а не в каждом обработчике: так невозможно
    забыть посчитать новый маршрут, а код ответа известен только после call_next.
    """
    request_id = uuid.uuid4().hex
    started = time.perf_counter()

    response = await call_next(request)

    duration = time.perf_counter() - started

    # Шаблон маршрута FastAPI кладёт в scope при сопоставлении адреса.
    # Берём именно шаблон "/orders/{order_id}", а не request.url.path ("/orders/17"):
    # иначе каждый номер заказа стал бы новым значением метки (кардинальность!).
    # Если ни один маршрут не подошёл (404 на /orderz), route в scope нет —
    # пишем одно общее значение "unmatched", а не сам адрес.
    route_obj = request.scope.get("route")
    route = route_obj.path if route_obj is not None else "unmatched"

    if route not in NOT_COUNTED:
        HTTP_REQUESTS.labels(
            method=request.method, route=route, status=str(response.status_code)
        ).inc()
        HTTP_REQUEST_DURATION.labels(route=route).observe(duration)

    response.headers["X-Request-ID"] = request_id
    log.info(
        "http_request",
        extra={
            "method": request.method,
            "route": route,
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 2),
            "request_id": request_id,
        },
    )
    return response


@app.exception_handler(RequestValidationError)
async def on_invalid_request(request: Request, exc: RequestValidationError):
    # Неверные данные заказа: считаем отказ с причиной "invalid",
    # ответ оставляем стандартным для FastAPI (422 с описанием ошибок).
    if request.method == "POST" and request.url.path == "/orders":
        ORDERS_REJECTED.labels(reason="invalid").inc()
    return await request_validation_exception_handler(request, exc)


# ------------------------------------------------------------------ маршруты


class OrderIn(BaseModel):
    drink: Literal["espresso", "americano", "latte", "cappuccino", "raf"]
    size: Literal["S", "M", "L"]


@app.post("/orders", status_code=202)
async def create_order(order_in: OrderIn):
    if worker.queue.qsize() >= worker.QUEUE_LIMIT:
        ORDERS_REJECTED.labels(reason="queue_full").inc()
        log.warning("order_rejected: queue_full")
        raise HTTPException(status_code=503, detail="Очередь заказов переполнена")

    order = worker.Order(id=next(order_ids), drink=order_in.drink, size=order_in.size)
    worker.ORDERS_DB[order.id] = order
    worker.queue.put_nowait(order)
    worker.update_queue_gauge()
    return {"order_id": order.id, "status": order.status}


@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    order = worker.ORDERS_DB.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return {
        "order_id": order.id,
        "drink": order.drink,
        "size": order.size,
        "status": order.status,
    }


@app.get("/menu")
async def menu():
    return {"drinks": worker.MENU, "sizes": ["S", "M", "L"]}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    # generate_latest(registry) — текст только из НАШЕГО реестра.
    # CONTENT_TYPE_LATEST — заголовок "text/plain; version=...": по нему
    # Prometheus понимает формат ответа.
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@app.get("/metrics/slow")
async def metrics_slow():
    # Только для опыта из prometheus/oshibki.yml: те же метрики, но через 2 с.
    # Задание "slow" ждёт 1 с (scrape_timeout) → "context deadline exceeded".
    # В рабочих настройках этот адрес не опрашивается.
    await asyncio.sleep(2)
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
