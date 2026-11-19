# Тесты Wokker Bot

## Запуск

```bash
# Установить pytest
pip install pytest

# Запустить все тесты
python -m pytest tests/ -v

# Запустить только security тесты
python -m pytest tests/test_security.py -v
```

## Структура

- `test_security.py` — тесты безопасности (хэширование, XSS, rate-limit)
- `test_routes.py` — тесты роутов (mock-запросы)
- `test_cache.py` — тесты кэширования
