# ilchenkodev-zapret

<p align="center">
  <img src="icon.png" width="128" height="128" alt="ilchenkodev-zapret icon">
</p>

Лёгкий tray-only инструмент для обхода замедлений и блокировок (YouTube, Discord и др.) на базе [zapret](https://github.com/bol-van/zapret) — `tpws` для macOS, `winws.exe` для Windows.

Приложение живёт **только в строке меню (macOS)** или **системном трее (Windows)** — никаких окон, никакой консоли.

---

## Скачать

Перейди в [**Releases**](../../releases) и скачай нужный файл:

| Платформа | Файл | Установка |
|-----------|------|-----------|
| macOS | `ilchenkodev-zapret-for-mac.dmg` | Открой `.dmg` → перетащи `.app` в Applications |
| Windows | `ilchenkodev-zapret-for-win.exe` | Запусти от имени **администратора** |

---

## Особенности

- **Tray-only** — нет Dock-иконки, нет окна, нет консоли
- **Автономный дистрибутив** — один `.app` или один `.exe`, без зависимостей
- **Выбор стратегии** — переключение между профилями обхода прямо из трея
- **Системный прокси** — автоматическая настройка SOCKS5 на macOS
- **Персистентный конфиг** — настройки и логи хранятся в:
  - macOS: `~/Library/Application Support/ILCHENKODEV-Bypass/`
  - Windows: `%APPDATA%\ILCHENKODEV-Bypass\`

---

## Запуск из исходного кода

### macOS
```bash
pip install pillow pystray pyobjc
python3 dist_mac/bypass_gui.py
```

### Windows
```cmd
pip install pillow pystray
python dist_win\bypass_gui.py
```

---

## Сборка

Автоматическая сборка через GitHub Actions при пуше тега `v*`.

### Ручная сборка (macOS)
```bash
cd dist_mac
pip install pyinstaller pillow pystray pyobjc
pyinstaller --noconfirm --clean ILCHENKODEV.spec
```

### Ручная сборка (Windows)
```cmd
cd dist_win
pip install pyinstaller pillow pystray
pyinstaller --noconfirm --clean ILCHENKODEV.spec
```

---

## Структура проекта

```
dist_mac/                — сборка для macOS
  bypass_gui.py          — основной скрипт
  ILCHENKODEV.spec       — конфиг PyInstaller
  icon.icns              — иконка приложения
  bin/mac/               — бинарники (tpws, mdig, ip2net)
  lists/                 — списки доменов и IP

dist_win/                — сборка для Windows
  bypass_gui.py          — основной скрипт
  ILCHENKODEV.spec       — конфиг PyInstaller
  icon.ico               — иконка приложения
  bin/                   — бинарники (winws.exe, WinDivert)
  lists/                 — списки доменов и IP
  *.bat                  — стратегии обхода

.github/workflows/       — CI/CD: автосборка и публикация релиза
```

---

## CI/CD

При пуше тега `v*` (например `v1.1.0`) автоматически:
1. Собирается `.app` → `ilchenkodev-zapret-for-mac.dmg`
2. Собирается `ilchenkodev-zapret-for-win.exe`
3. Создаётся GitHub Release с обоими файлами

---

## Лицензия

Основан на [zapret](https://github.com/bol-van/zapret) от bol-van.
