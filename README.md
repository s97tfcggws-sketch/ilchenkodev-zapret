# ilchenkodev-zapret

<p align="center">
  <img src="icon.png" width="128" height="128" alt="ilchenkodev-zapret">
</p>

Лёгкий tray-only инструмент для обхода замедлений и блокировок (YouTube, Discord и др.) на базе [zapret](https://github.com/bol-van/zapret) — `tpws` для macOS, `winws.exe` для Windows.

Приложение живёт **только в строке меню (macOS)** или **системном трее (Windows)** — никаких окон, никакой консоли.

---

## Скачать

Перейди в [**Releases**](../../releases) и скачай нужный файл:

| Платформа | Файл | Установка |
|-----------|------|-----------|
| macOS | `ilchenkodev-zapret-for-mac.dmg` | Открой `.dmg` → перетащи в Applications |
| Windows | `ilchenkodev-zapret-for-win.exe` | Запусти от имени **администратора** |

---

## Особенности

- **Tray-only** — нет Dock-иконки, нет окна, нет консоли
- **Один файл** — `.app` или `.exe`, без зависимостей
- **Стратегии обхода** — переключение из трея
- **Системный прокси** — автоматический SOCKS5 на macOS
- **Конфиг** — настройки и логи хранятся в:
  - macOS: `~/Library/Application Support/ILCHENKODEV-Bypass/`
  - Windows: `%APPDATA%\ILCHENKODEV-Bypass\`

---

## Запуск из исходников

### macOS
```bash
pip install pillow pystray pyobjc
python3 dist_mac/app.py
```

### Windows
```cmd
pip install pillow pystray
python dist_win\app.py
```

---

## Сборка

Автоматическая сборка через GitHub Actions при пуше тега `v*`.

### Ручная сборка (macOS)
```bash
cd dist_mac
pip install pyinstaller pillow pystray pyobjc
pyinstaller --noconfirm --clean zapret.spec
```

### Ручная сборка (Windows)
```cmd
cd dist_win
pip install pyinstaller pillow pystray
pyinstaller --noconfirm --clean zapret.spec
```

---

## Структура проекта

```
dist_mac/
  app.py              — основной скрипт
  zapret.spec          — конфиг PyInstaller
  icon.icns            — иконка приложения
  dmg-background.png   — фон DMG-установщика
  bin/mac/             — бинарники (tpws, mdig, ip2net)
  lists/               — списки доменов

dist_win/
  app.py              — основной скрипт
  zapret.spec          — конфиг PyInstaller
  icon.ico             — иконка приложения
  bin/                 — бинарники (winws.exe, WinDivert)
  lists/               — списки доменов
  *.bat                — стратегии обхода

.github/workflows/     — CI/CD
```

---

## CI/CD

При пуше тега `v*` (например `v1.2.0`) автоматически:
1. Собирается `.app` → `ilchenkodev-zapret-for-mac.dmg`
2. Собирается `ilchenkodev-zapret-for-win.exe`
3. Создаётся GitHub Release с обоими файлами

---

## Лицензия

Основан на [zapret](https://github.com/bol-van/zapret) от bol-van.
