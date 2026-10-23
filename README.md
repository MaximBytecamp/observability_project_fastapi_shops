# Coffee Monitoring

Сервис приёма заказов кофейни на FastAPI со стеком мониторинга Prometheus + Pushgateway + Grafana.

![Схема стенда](docs/schema.png)

- **api** — принимает заказы, готовит их в фоновых обработчиках, отдаёт метрики на `/metrics`.
- **Prometheus** — опрашивает `api`, `pushgateway` и себя каждые 15 с (pull).
- **Pushgateway** — принимает метрики от короткой задачи `report_job` (push).
- **Grafana** — дашборд «Кофейня · заказы», подключается автоматически.

## Запуск

Нужны Docker с Compose v2 и Python 3 (для генератора нагрузки).

```bash
docker compose up -d --build          # запуск
docker compose run --rm report_job    # ночной отчёт → Pushgateway
python3 load/load.py normal           # нагрузка: normal | rush | bad
docker compose down                   # остановка (-v — удалить данные)
```

| Сервис | Адрес |
|---|---|
| API | http://127.0.0.1:8030 (`/docs`, `/metrics`) |
| Prometheus | http://127.0.0.1:9097 |
| Pushgateway | http://127.0.0.1:9098 |
| Grafana | http://127.0.0.1:3017 (admin / admin) |

Порты открыты только на `127.0.0.1`.

## API

| Метод и путь | Описание | Ответы |
|---|---|---|
| `POST /orders` | создать заказ `{"drink": "latte", "size": "M"}` | 202; 422 — неверные данные; 503 — очередь заполнена (50) |
| `GET /orders/{order_id}` | статус: `queued`, `preparing`, `ready`, `failed` | 200; 404 |
| `GET /menu` | espresso, americano, latte, cappuccino, raf | 200 |
| `GET /health` | проверка живости | 200 |
| `GET /metrics` | метрики Prometheus | 200 |

## Конфигурация

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `BARISTAS` | `6` | число фоновых обработчиков заказов |
| `SLOW_MODE` | `0` | `1` — приготовление в 3 раза дольше |
| `PROM_CONFIG` | `prometheus.yml` | файл настроек Prometheus (`oshibki.yml` — с намеренными ошибками scrape) |
| `PUSHGATEWAY_URL` | `pushgateway:9091` | адрес Pushgateway для `report_job` |

## Метрики

| Метрика | Тип |
|---|---|
| `coffee_http_requests_total{method,route,status}` | counter |
| `coffee_http_request_duration_seconds{route}` | histogram |
| `coffee_orders_total{drink,result}` | counter |
| `coffee_order_prepare_seconds{drink}` | histogram |
| `coffee_orders_rejected_total{reason}` | counter |
| `coffee_queue_length` | gauge |
| `coffee_baristas_busy` | gauge |
| `coffee_daily_report_last_success_timestamp_seconds` | gauge |
| `coffee_daily_report_duration_seconds` | gauge |
| `coffee_daily_report_orders` | gauge |

Примеры запросов:

```
sum by (result) (rate(coffee_orders_total[1m])) * 60                                  # заказов в минуту
histogram_quantile(0.95, sum by (le, drink) (rate(coffee_order_prepare_seconds_bucket[5m])))  # p95 приготовления
time() - coffee_daily_report_last_success_timestamp_seconds                           # возраст отчёта, с
```

## Структура

```
app/            API: маршруты, метрики, фоновые обработчики, JSON-логи
report_job/     ночной отчёт с отправкой метрик в Pushgateway
prometheus/     настройки Prometheus
grafana/        provisioning источника данных и дашборда
load/           генератор нагрузки
compose.yaml
```

## Ограничения

Заказы и очередь хранятся в памяти процесса и теряются при перезапуске. Grafana
с анонимным просмотром и паролем по умолчанию, Prometheus и Pushgateway без
авторизации, алертов нет — перед реальным использованием это нужно закрыть.
