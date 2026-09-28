# AI Edu backend

Django REST API и инфраструктура платформы: PostgreSQL, Redis и MinIO. Frontend находится в отдельном репозитории и подключается к общей Docker-сети `aiedu-platform`.

## Запуск backend

1. Скопируйте `.env.example` в `.env` и замените значения `replace-with-...` случайными секретами.
2. Выполните из корня этого репозитория:

```bash
docker compose up --build -d
```

Compose поднимает PostgreSQL, Redis, MinIO и backend, запускает миграции и создаёт bucket. Backend API доступен в Docker-сети по `http://backend:8000` и локально на `http://localhost:8000`. MinIO Console доступна только локально на `http://localhost:9001`.

Создайте администратора платформы:

```bash
docker compose exec backend python manage.py create_platform_admin --email admin@example.com
```

Команда запросит пароль. Этот аккаунт получает роль `ADMIN`, но не системные права Django. Для системного superuser используйте отдельную команду Django `createsuperuser`.

Демо-данные можно добавить повторно без дубликатов:

```bash
docker compose exec backend python manage.py seed_demo
```

API использует `/api/v1/`. OpenAPI схема доступна по `/api/v1/schema/`, Swagger UI — `/api/v1/docs/`. Изображения хранятся в приватном MinIO bucket и выдаются через авторизованный endpoint backend.

## Переменные окружения

`.env.example` включает настройки Django, PostgreSQL, MinIO и лимит загрузки. Секреты хранятся только в локальном `.env`, который игнорируется Git. В production задайте `DEBUG=false`, сильный `SECRET_KEY`, `ALLOWED_HOSTS` и `CSRF_TRUSTED_ORIGINS` для своего HTTPS-домена.

## Production

Сначала запустите backend с production-конфигурацией:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Production backend использует Gunicorn и создаёт общий volume `aiedu-static` для Django static files. Затем в репозитории frontend запустите его production Compose; Nginx подключается к общей сети и этому volume. TLS должен завершаться на внешнем reverse proxy с заголовком `X-Forwarded-Proto: https`.

## Проверки

```bash
docker compose exec -T backend python manage.py check
docker compose exec -T backend python manage.py test apps.assessments
docker compose exec -T backend python manage.py smoke_mvp
docker compose exec -T backend python manage.py spectacular --validate --file /tmp/schema.yaml
```

`smoke_mvp` проверяет API, PostgreSQL, загрузку в MinIO и прохождение теста, после чего удаляет созданные записи. Неиспользуемые изображения можно посмотреть через `cleanup_unused_media`, удалить — с `--delete`.
