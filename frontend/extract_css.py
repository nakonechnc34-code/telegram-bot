# -*- coding: utf-8 -*-
import re
from pathlib import Path

html_file = Path("admin.html")
css_file = Path("admin.css")

if not html_file.exists():
    print("❌ Ошибка: admin.html не найден в этой папке")
    exit()

print("⏳ Читаю admin.html...")
html = html_file.read_text(encoding="utf-8")

# Ищем блок <style>...</style>
match = re.search(r'<style>(.*?)</style>', html, re.DOTALL)

if not match:
    print("⚠️ Тег <style> не найден. Возможно, CSS уже вынесен в отдельный файл.")
    exit()

print("✂️ Вырезаю стили...")
css_content = match.group(1).strip()

# Сохраняем CSS в отдельный файл
css_file.write_text(css_content, encoding="utf-8")
print(f"✅ Создан файл admin.css ({len(css_content)} байт)")

# Заменяем блок <style>...</style> на ссылку <link>
new_html = html.replace(match.group(0), '<link rel="stylesheet" href="/admin.css">')
html_file.write_text(new_html, encoding="utf-8")

print("✅ admin.html обновлен!")
print(f"📉 Размер HTML уменьшился примерно на {len(css_content) // 1024} КБ.")
print("🚀 Готово! Теперь браузер будет кэшировать стили.")
