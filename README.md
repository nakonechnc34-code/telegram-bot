# Wokker Bot — Корпоративная система для сотрудников сети ресторанов

Бот для внутренней коммуникации и доступа к информации о ресторанах Wokker.

## Функционал

- **Регистрация сотрудника**: ФИО, телефон, дата рождения, должность, ресторан
- **Справочник ресторанов**: адреса, часы работы, телефоны, ссылка на Яндекс Карты
- **Админ-панель**: список пользователей, блокировка/разблокировка, удаление, статистика
- **Табель учёта**: учёт часов, отпусков, больничных
- **Медкнижки**: отслеживание сроков врачей, анализов, прививок
- **Академия**: обучение и сертификация сотрудников
- **Push-уведомления**: через Telegram Web App

## Стек технологий

- **Backend**: Python 3.11, aiohttp
- **Database**: PostgreSQL
- **Frontend**: Vanilla JS, CSS (PWA)
- **Deployment**: Amvera / Docker

## Установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/nakonechnc34-code/telegram-bot.git
cd telegram-bot

# 2. На环境变量
cp .env.example .env
# Заполнить .env

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Запустить
python app.py
```

## Docker

```bash
docker build -t wokker-bot .
docker run -p 8080:8080 --env-file .env wokker-bot
```

## Тесты

```bash
pip install pytest
python -m pytest tests/ -v
```

## Environment Variables

| Переменная | Описание | Обязательная |
|------------|----------|--------------|
| DATABASE_URL | PostgreSQL connection string | ✅ |
| ADMIN_LOGIN | Логин супер-админа | ✅ |
| ADMIN_PASSWORD | Пароль супер-админа | ✅ |
| VAPID_PUBLIC_KEY | Ключ для push-уведомлений | ❌ |
| VAPID_PRIVATE_KEY | Приватный ключ для push | ❌ |
| SENTRY_DSN | DSN для Sentry | ❌ |
| PORT | Порт сервера | ❌ (8080) |

## Структура

```
├── app.py              # Точка входа
├── config.py           # Конфигурация
├── db.py              # Работа с БД
├── middleware/         # Middleware (auth, cache, rate-limit)
├── routes/            # API роуты
│   ├── auth.py        # Аутентификация
│   ├── users.py       # Управление пользователями
│   ├── core.py        # Основная логика
│   ├── timesheet.py   # Табель
│   ├── academy.py     # Академия
│   ├── medbooks.py    # Медкнижки
│   └── content.py     # Новости, стандарты, FAQ
├── utils/             # Утилиты
│   ├── security.py    # Хэширование, XSS
│   ├── auth_helpers.py # Аутентификация
│   └── common.py      # Общие функции
├── frontend/          # Web App UI
└── tests/             # Unit-тесты
```

## Безопасность

- Rate limiting на вход и API
- XSS защита через bleach
- Path traversal защита
- Security headers (CSP, HSTS, X-Frame-Options)
- Admin audit log
