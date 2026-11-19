# =====================
# Stage 1: Build (не обязателен, просто установка зависимостей)
# =====================
FROM python:3.11-slim AS base

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем только requirements для кэширования Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Создаём папку для загрузок
RUN mkdir -p /app/uploads

# Открываем порт
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# Команда запуска
CMD ["python", "app.py"]
