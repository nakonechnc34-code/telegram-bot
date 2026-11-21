# DeepSeek AI — настройка

## 1. Получение API ключа

1. Зарегистрируйся: https://platform.deepseek.com
2. При регистрации дают бесплатные кредиты (~$5)
3. Перейди в **API Keys** → **Create API Key**
4. Скопируй ключ (начинается с `sk-...`)

## 2. Настройка в проекте

Добавь в `.env`:

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Опционально:
# DEEPSEEK_MODEL=deepseek-chat       # или deepseek-coder
# DEEPSEEK_BASE_URL=https://api.deepseek.com
```

## 3. API эндпоинты

### Чат `/api/ai/chat`

```http
POST /api/ai/chat
Authorization: Bearer <webToken>
Content-Type: application/json

{
  "message": "Как пройти сертификацию?",
  "mode": "default",    // "default" или "faq"
  "clear": false        // true = очистить историю
}
```

**Ответ:**
```json
{
  "response": "Для прохождения сертификации...",
  "tokens_used": 156.0
}
```

### История `/api/ai/history`

```http
GET /api/ai/history
Authorization: Bearer <webToken>
```

**Ответ:**
```json
{
  "history": [
    {"role": "user", "content": "Привет"},
    {"role": "assistant", "content": "Здравствуйте!"}
  ]
}
```

### Очистка истории `/api/ai/clear`

```http
POST /api/ai/clear
Authorization: Bearer <webToken>
```

## 4. Проверка

Запусти сервер и посмотри логи:

```
🤖 AI (DeepSeek): deepseek-chat — активен
```

Если не настроен:

```
🤖 AI (DeepSeek): не настроен (DEEPSEEK_API_KEY)
⚠️ DEEPSEEK_API_KEY не задан. AI-функции бота работать не будут.
```

## 5. Стоимость

DeepSeek очень дёшевый:
- `deepseek-chat` — ~$0.001 за 1K токенов (вход + выход)
- Средний диалог — ~$0.001–0.005

Бесплатных кредитов хватит на ~5000–10000 диалогов.
