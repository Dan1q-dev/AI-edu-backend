# AI Edu backend

Backend виртуальной работы №1 `lecture_workshop@1.0.0`: [настройка AI API, локальный worker, API и схема документа](docs/workspace.md).

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

Production backend использует Gunicorn и создаёт volume `aiedu-static` для Django static files. Затем в репозитории frontend запустите его production Compose. Внешний Nginx направляет API на backend и раздаёт Django static files из этого volume. TLS завершается на Nginx с передачей заголовка `X-Forwarded-Proto: https`.

Production-домен платформы — `https://aiedu.com.kz`. В серверном `.env` задайте:

```dotenv
DEBUG=false
ALLOWED_HOSTS=aiedu.com.kz,localhost,127.0.0.1,backend
CSRF_TRUSTED_ORIGINS=https://aiedu.com.kz
```

`ALLOWED_HOSTS` содержит имена хостов без протокола, `CSRF_TRUSTED_ORIGINS` — полные HTTPS origins. Backend читает существующий `.env` при создании контейнера; обновление исходников не заменяет этот файл. API браузера использует тот же домен и пути `/api/v1/`, поэтому отдельный CORS middleware не требуется. Cookie остаются привязанными к текущему хосту; после смены домена войдите заново.

В HTTPS server block внешнего Nginx укажите `server_name aiedu.com.kz` и сертификат этого домена. Маршруты должны сохранять исходный Host и протокол:

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:4000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
    proxy_read_timeout 180s;
}

location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

После изменения `.env` выполните в каталоге серверного backend следующие команды. Они сохраняют образ и тег текущего контейнера, в том числе если CI передавал тег только через окружение:

```bash
backend_image=$(docker inspect --format '{{.Config.Image}}' ai-edu-backend-1)
BACKEND_IMAGE="${backend_image%:*}" IMAGE_TAG="${backend_image##*:}" \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --no-deps --no-build --force-recreate backend
```

Если меняли Nginx, примените конфигурацию через `sudo nginx -t && sudo systemctl reload nginx`.
Проверка: `curl -i https://aiedu.com.kz/api/v1/csrf/` должен вернуть `200`. Без сессии `/api/v1/auth/me/` возвращает `403`, после входа — `200`. Ответ `400` на оба GET обычно означает отклонённый Host; проверьте значения в контейнере:

```bash
docker exec ai-edu-backend-1 python -c "from config import settings; print(settings.ALLOWED_HOSTS); print(settings.CSRF_TRUSTED_ORIGINS)"
```

## Проверки

```bash
docker compose exec -T backend python manage.py check
docker compose exec -T backend python manage.py test apps.assessments
docker compose exec -T backend python manage.py smoke_mvp
docker compose exec -T backend python manage.py spectacular --validate --file /tmp/schema.yaml
```

`smoke_mvp` проверяет API, PostgreSQL, загрузку в MinIO и прохождение теста, после чего удаляет созданные записи. Неиспользуемые изображения можно посмотреть через `cleanup_unused_media`, удалить — с `--delete`.

## Practice Engine

`LearningItem(PRACTICE)` задаёт положение в модуле и ссылается на `PracticeDefinition` и опубликованную `PracticeVersion`. Условия задания, конфигурация и критерии принадлежат версии. Сохранение редактора меняет только черновик; публикация создаёт следующую неизменяемую версию. Название и описание также фиксируются в версии. Начатая `PracticeSubmission` сохраняет свою версию при обновлении публикации. Новая попытка использует текущую публикацию.

`PracticeResult` хранит оценку отдельно от ответа: `self_assessment_score`, `automatic_score`, `teacher_score`, `effective_score`, `grading_source`, `psi_value`, `psi_source`. Реализован только `checklist_practice@1.0.0` с источником `SELF_ASSESSMENT`. Сервер принимает состояния критериев и вычисляет Ψ = отмеченные / все критерии. Обязательные критерии определяют завершение: все обязательные отмечены — 100% через существующий сервис прогресса; иначе сохраняется частичный процент. Необязательные критерии тоже входят в Ψ. Автоматической проверки содержания работы нет.

API под `/api/v1/`:

| Метод и адрес | Назначение |
| --- | --- |
| `GET practice-types/` | Manifest, capabilities, схема, идентификаторы редактора/runtime |
| `GET items/{short_id}/practice/draft/` | Черновик, публикация и версии; только администратор |
| `PUT items/{short_id}/practice/draft/` | Сохранить `{practice_type, plugin_version, title, description, config}` |
| `POST items/{short_id}/practice/draft/` | Опубликовать сохранённый черновик |
| `GET items/{short_id}/practice/` | Условия закреплённой версии, своя попытка, результат и прогресс |
| `POST items/{short_id}/practice/start/` | Начать попытку или вернуть уже начатую |
| `POST items/{short_id}/practice/` | Сдать `{submission_id, submission_data: {checks: [true, false]}}` |
| `GET items/{short_id}/practice/history/` | Своя история с пагинацией |

Чужие попытки недоступны. Проверки Course Access, публикации и блокировок модулей применяются ко всем student endpoints. Повторная отправка одинакового ответа идемпотентна; изменение сданного ответа требует новой попытки. Снимок критериев и ответов сохраняется при сдаче. Повторное прохождение после неуспешного теста помечает прежнюю попытку неактуальной, сохраняя её историю и оценку. Формула Ω не изменена: она получает числовой Ψ из результата, а источник остаётся в базе. Удаление практики или родительского материала с попытками запрещено.

Миграции переносят старые `LearningItem.practice_criteria` в версии и `PracticeCriterion`, существующие самооценки — в закреплённые submissions/results, сохраняя прежний прогресс и время активности. Несовпадающие старые критерии сохраняются отдельной исторической версией. Legacy `PracticeDefinition.kind/config` и снимки `PracticeSubmission.criteria/checks` сохранены для совместимости данных; новые типы используют version config и `submission_data/criteria_snapshot`. Ненастроенные старые практики требуют выбора типа в редакторе.

Перед запуском обновлённого приложения выполните `python manage.py migrate` (Docker Compose выполняет это автоматически). Откат к старой модели с одной сдачей на пользователя несовместим с несколькими новыми попытками; для такого отката восстановите резервную копию базы.

Добавление типа независимым разработчиком:

1. Реализовать контракт `PracticePlugin` в `apps/activities/registry.py`: manifest, `validate_config`, `materialize_config`, `evaluate`. Manifest содержит JSON schema. Валидатор обязан строго проверять ту же схему; `evaluate` рассчитывает оценку на сервере и возвращает `Evaluation` с источником, признаком завершения и снимком. Зарегистрировать конкретную версию через `registry.register(plugin)`.
2. На frontend реализовать `PracticePlugin` из `src/practice/types.ts`: `ConfigEditor`, `StudentRuntime`, `initialConfig`, `validateConfig`, и вызвать `registerPractice` в `src/practice/registry.ts`. Версия плагина должна совпадать с backend manifest. Каталог показывает только зарегистрированные backend типы; карточка отключена, если frontend реализации нет.
3. При несовместимом изменении схемы зарегистрировать новую версию плагина, оставив старую доступной для закреплённых попыток. Добавить проверки схемы, серверного оценивания, доступа и сохранения версии. Изменений Curriculum и формулы Ω для регистрации типа не требуется.

Проверки ядра: `python manage.py test apps.activities apps.education.test_adaptive`.
