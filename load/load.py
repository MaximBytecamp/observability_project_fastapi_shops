"""Генератор нагрузки для API кофейни. Только стандартная библиотека Python.

    python load/load.py normal     # 2 заказа/с, 3 минуты
    python load/load.py rush       # 10 заказов/с, 1 минута: очередь переполняется, 503
    python load/load.py bad        # 20 % запросов с ошибками (422 и 404)

    python load/load.py normal --duration 30           # укоротить сценарий
    python load/load.py rush --url http://127.0.0.1:8030

В конце печатает, сколько запросов отправлено и с какими кодами.
"""

import argparse
import json
import random
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

DRINKS = ["espresso", "americano", "latte", "cappuccino", "raf"]
SIZES = ["S", "M", "L"]

# сценарий: (заказов в секунду, длительность в секундах, доля «плохих» запросов)
SCENARIOS = {
    "normal": (2, 180, 0.0),
    "rush": (10, 60, 0.0),
    "bad": (2, 60, 0.2),
}

results: Counter = Counter()
order_ids: list[int] = []
lock = threading.Lock()


def request(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict | None]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, None  # 0 = API не ответил (например, контейнер остановлен)


def record(label: str, status: int) -> None:
    with lock:
        results[(label, status)] += 1


def good_order(base: str) -> None:
    body = {"drink": random.choice(DRINKS), "size": random.choice(SIZES)}
    status, payload = request(base, "POST", "/orders", body)
    record("POST /orders", status)
    if status == 202 and payload:
        with lock:
            order_ids.append(payload["order_id"])
    # Иногда клиент проверяет статус одного из прошлых заказов.
    if random.random() < 0.5:
        with lock:
            oid = random.choice(order_ids) if order_ids else None
        if oid is not None:
            status, _ = request(base, "GET", f"/orders/{oid}")
            record("GET /orders/{id}", status)


def bad_request(base: str) -> None:
    kind = random.choice(["bad_drink", "no_size", "missing_order", "wrong_route"])
    if kind == "bad_drink":
        status, _ = request(base, "POST", "/orders", {"drink": "mojito", "size": "M"})
        record("POST /orders (неверный напиток)", status)
    elif kind == "no_size":
        status, _ = request(base, "POST", "/orders", {"drink": "latte"})
        record("POST /orders (нет размера)", status)
    elif kind == "missing_order":
        status, _ = request(base, "GET", f"/orders/{random.randint(10**6, 10**7)}")
        record("GET /orders/{id} (нет заказа)", status)
    else:
        status, _ = request(base, "GET", "/orderz")
        record("GET /orderz (нет маршрута)", status)


def main() -> None:
    parser = argparse.ArgumentParser(description="Нагрузка на API кофейни")
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--url", default="http://127.0.0.1:8030")
    parser.add_argument("--duration", type=int, help="длительность, с (по умолчанию из сценария)")
    args = parser.parse_args()

    rate, duration, bad_share = SCENARIOS[args.scenario]
    if args.duration:
        duration = args.duration
    base = args.url.rstrip("/")

    print(f"Сценарий {args.scenario}: {rate} запр./с, {duration} с, "
          f"ошибочных {int(bad_share * 100)} % → {base}")

    started = time.monotonic()
    total = rate * duration
    with ThreadPoolExecutor(max_workers=50) as pool:
        for i in range(total):
            # Ровный темп: i-й запрос уходит в момент started + i / rate.
            delay = started + i / rate - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            fn = bad_request if random.random() < bad_share else good_order
            pool.submit(fn, base)
            if (i + 1) % (rate * 10) == 0:
                print(f"  прошло {int(time.monotonic() - started)} с, отправлено {i + 1}")

    print("\nИтог: запросов отправлено", sum(results.values()))
    for (label, status), count in sorted(results.items()):
        code = status if status else "нет ответа"
        print(f"  {label:<36} {code!s:>10}  × {count}")


if __name__ == "__main__":
    main()
