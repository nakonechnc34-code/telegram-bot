"""Общие утилиты, используемые в нескольких модулях."""
import random

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"
}

def safe_int(val, default=0):
    """Безопасно преобразует значение в int."""
    try:
        return int(val)
    except (ValueError, TypeError, OverflowError):
        return default

def safe_float(val, default=0.0):
    """Безопасно преобразует значение в float."""
    try:
        return float(str(val).replace(',', '.'))
    except (ValueError, TypeError, OverflowError):
        return default

def generate_login_for(full_name, existing_logins):
    """Генерирует уникальный логин из ФИО."""
    parts = (full_name or "").strip().split()
    surname = (parts[0] if parts else "").lower()
    letters = ""
    for ch in surname:
        if len(letters) >= 3:
            break
        t = TRANSLIT.get(ch)
        if t:
            letters += t
    while len(letters) < 3:
        letters += random.choice("abcdefghijklmnopqrstuvwxyz")
    letters = letters[:3]

    digits = list(range(10, 100))
    random.shuffle(digits)
    for d in digits:
        candidate = f"{letters}{d}"
        if candidate not in existing_logins:
            return candidate

    for _ in range(500):
        rl = "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(3))
        d = random.randint(10, 99)
        candidate = f"{rl}{d}"
        if candidate not in existing_logins:
            return candidate

    raise RuntimeError("Не удалось сгенерировать логин")
