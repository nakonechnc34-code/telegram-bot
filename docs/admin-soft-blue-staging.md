# WOKKER Control Soft Blue — изолированный тестовый стенд

Этот стек **не развёрнут автоматически**. Он запускается отдельно на компьютере или тестовом сервере с Docker. Используется ветка `chore/admin-soft-blue-staging`, включающая PR #5–#10. Рабочий Amvera-проект не изменяется.

## Запуск

1. Получите код ветки `chore/admin-soft-blue-staging`.
2. Создайте локальный файл `.env.staging` (не коммитьте его) с тремя уникальными секретами:
   ```dotenv
   STAGING_DB_PASSWORD=REPLACE_WITH_UNIQUE_STRONG_PASSWORD
   STAGING_ADMIN_LOGIN=adm01
   STAGING_ADMIN_PASSWORD=REPLACE_WITH_UNIQUE_STRONG_PASSWORD
   ```
3. Выполните `docker compose --env-file .env.staging -f compose.staging.yaml up -d --build`.
4. Проверьте `http://127.0.0.1:18080/api/health`, затем откройте `http://127.0.0.1:18080/admin`.
5. Проведите сценарии из `docs/admin-soft-blue-acceptance.md` с синтетическими тестовыми сотрудниками и медкнижками.

## Границы безопасности

- Стенд доступен только с локальной машины (127.0.0.1). Для доступа коллег используйте защищённый SSH-туннель или отдельно согласованную тестовую инфраструктуру с HTTPS и ограничением доступа.
- PostgreSQL отдельный, **без** опубликованного порта; данные хранятся в собственном томе `staging_db`. Загрузки — в отдельном `staging_uploads`.
- Не копируйте `DATABASE_URL`, Telegram-токены, push-ключи, персональные данные или файлы медкнижек из production.
- Не подключайте этот стенд к рабочему Telegram-боту или другим production-интеграциям.
- `docker compose --env-file .env.staging -f compose.staging.yaml down` останавливает стек без удаления данных. `down -v` **удаляет тестовые данные**, использовать осознанно.
- Для внешнего адреса Amvera необходимо **отдельное** тестовое приложение, отдельная PostgreSQL и отдельное хранилище; публикация не выполняется этим PR.
- Не сливать PR и не выпускать в production, пока ручная приёмка не пройдена.

## Проверка

`docker compose --env-file .env.staging -f compose.staging.yaml ps`

`curl -fsS http://127.0.0.1:18080/api/health`

При отсутствии статуса healthy изучить `docker compose --env-file .env.staging -f compose.staging.yaml logs --tail=100 app db`.
