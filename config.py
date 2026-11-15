import os
import logging
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ============= SECURITY & ENV SETTINGS =============
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: DATABASE_URL не задан")

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@wokker.ru")}

ENABLE_PUSH = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)
if not ENABLE_PUSH:
    logging.warning("⚠️ VAPID ключи не заданы. Push-уведомления работать не будут.")

ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "adm01").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения ADMIN_PASSWORD не задана!")

APP_ENV = os.getenv("ENV", "development").lower()
LOGIN_RE = re.compile(r"^[a-z]{3}\d{2}$")
SESSION_TTL_DAYS = 30
SESSION_CACHE_TTL = 30  # секунд

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

PERMISSIONS_LIST = [
    {"key": "users_create", "label": "Добавлять сотрудников"},
    {"key": "users_edit", "label": "Редактировать сотрудников"},
    {"key": "users_fire", "label": "Увольнять сотрудников"},
    {"key": "citizenships_edit", "label": "Управлять гражданствами"},
    {"key": "medbook_edit", "label": "Заполнять медкнижки"},
    {"key": "medbook_doctors_manage", "label": "Врачи: добавление и сроки"},
    {"key": "medbook_tests_manage", "label": "Анализы: добавление и сроки"},
    {"key": "medbook_vaccines_manage", "label": "Прививки: добавление и сроки"},
    {"key": "restaurant_tu", "label": "Менять ТУ у ресторанов"},
    {"key": "restaurant_create", "label": "Добавлять рестораны"},
    {"key": "restaurant_edit", "label": "Редактировать рестораны"},
    {"key": "standards_edit", "label": "Предлагать стандарты"},
    {"key": "checklist_create", "label": "Создавать чек-листы"},
    {"key": "checklist_edit", "label": "Редактировать чек-листы"},
    {"key": "news_write", "label": "Писать новости"},
    {"key": "news_edit", "label": "Редактировать новости"},
    {"key": "news_suggest", "label": "Предлагать новости"},
    {"key": "faq_edit", "label": "Редактировать FAQ"},
    {"key": "positions_edit", "label": "Управлять должностями"},
    {"key": "questions_reply", "label": "Отвечать на вопросы"},
    {"key": "certification_edit", "label": "Управлять вопросами сертификации"},
    {"key": "academy_edit", "label": "Управлять Академией"},
    {"key": "timesheet_access", "label": "Доступ к Табелю"},
]
PERM_KEYS = [p["key"] for p in PERMISSIONS_LIST]
