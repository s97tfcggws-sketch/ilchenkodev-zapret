# ILCHENKODEV Bypass

Лёгкий tray-only GUI для обхода замедлений и блокировок (YouTube, Discord и др.) на базе утилит [zapret](https://github.com/bol-van/zapret) — `tpws` для macOS и `winws.exe` для Windows.

Приложение живёт **только в строке меню (macOS)** или **системном трее (Windows)** — никаких окон, никакой консоли.

---

## ✨ Особенности

- **Tray-only** — нет Dock-иконки, нет окна, нет консоли
- **Автономный дистрибутив** — один `.app` или один `.exe` без зависимостей
- **Умный выбор стратегии** — переключение между профилями прямо из трея
- **Системный прокси** — автоматически настраивает SOCKS5 прокси на macOS
- **Персистентные настройки** — конфиг и лог хранятся в пользовательской директории
  - macOS: `~/Library/Application Support/ILCHENKODEV-Bypass/`
  - Windows: `%APPDATA%\ILCHENKODEV-Bypass\`
- **Фирменные иконки** — `tray-active.png` (зелёный) / `tray-inactive.png` (серый)

---

## 🚀 Скачать готовую версию

Перейди в раздел [**Releases**](../../releases) и скачай нужный файл:

| Платформа | Файл | Установка |
|-----------|------|-----------|
| macOS | `ILCHENKODEV-macOS.dmg` | Открой `.dmg`, перетащи `.app` в Applications |
| Windows | `ILCHENKODEV.exe` | Запусти от имени **администратора** |

---

## 🔧 Запуск из исходного кода

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

## 📦 Сборка вручную

Сборка происходит автоматически через GitHub Actions при пуше тега `v*`.
Для ручной сборки локально:

### macOS
```bash
cd dist_mac
pip install pyinstaller pillow pystray pyobjc
pyinstaller --noconfirm --clean ILCHENKODEV.spec
```

### Windows
```cmd
cd dist_win
pip install pyinstaller pillow pystray
pyinstaller --noconfirm --clean ILCHENKODEV.spec
```

---

## 📁 Структура проекта

```
dist_mac/               — исходники и ресурсы для macOS-сборки
  bypass_gui.py         — основной скрипт приложения
  ILCHENKODEV.spec      — конфиг PyInstaller
  icon.icns             — иконка приложения (macOS)
  tray-active.png       — иконка трея (активен)
  tray-inactive.png     — иконка трея (выключен)
  bin/mac/              — нативные бинарники (tpws, mdig, ip2net)
  lists/                — списки доменов и IP

dist_win/               — исходники и ресурсы для Windows-сборки
  bypass_gui.py         — основной скрипт приложения
  ILCHENKODEV.spec      — конфиг PyInstaller
  icon.ico              — иконка приложения (Windows)
  tray-active.png       — иконка трея (активен)
  tray-inactive.png     — иконка трея (выключен)
  bin/                  — нативные бинарники (winws.exe, WinDivert и др.)
  lists/                — списки доменов и IP
  utils/                — вспомогательные файлы
  *.bat                 — стратегии обхода

.github/workflows/      — CI/CD: автосборка и публикация релиза
```

---

## ☁️ GitHub Actions CI/CD

При пуше тега `v*` (например `v1.0.8`) автоматически:
1. Собирается `.app` + `.dmg` для macOS
2. Собирается `.exe` для Windows
3. Создаётся GitHub Release с обоими файлами
