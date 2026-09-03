# SSD Health

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](#лиценз)
[![smartctl](https://img.shields.io/badge/requires-smartctl-orange.svg)](https://www.smartmontools.org/)

Терминална програма на Python, която показва **здравето на SSD и HDD** чрез SMART данни.

If you have any questions about install, or need free translation to ENG or any other please contact me: 
good.vibes.github@gmail.com
Free to use by anyone private or business in all countries. 
Free to change anything depend to your whims.

Автоматично намира дисковете, чете `smartctl` и дава оценка 0–100% плюс температура, износване, резервни блокове, работни часове и проблемни сектори.

Работи на **Linux**, **Windows** и **macOS**. Изходът е на български.

---

## Какво показва

За всеки открит диск:

| Поле | Значение |
|---|---|
| SMART статус | `PASSED` / `FAILED` — самооценката на самия диск |
| Оценка здраве | 0–100% + присъда (ОТЛИЧНО / ДОБРО / ВНИМАНИЕ / ЛОШО / КРИТИЧНО) |
| Температура | текуща °C |
| Оставащ ресурс | износване на NAND при SSD / NVMe |
| Резервни блокове | Available Spare при NVMe |
| Работни часове | колко време е работил дискът |
| Записани / прочетени данни | приблизителен обем |
| Преразпределени / чакащи сектори | ранни признаци за повреда |

Оценката е ориентир, не присъда. **SMART не гарантира бъдещето — прави резервни копия.**

### Как да четеш оценката

| Здраве | Значение |
|---|---|
| ≥ 90% | отлично |
| 75–89% | добре |
| 50–74% | внимание — следи износването и температурата |
| < 50% или `FAILED` | архивирай и планирай смяна |

---

## Изисквания

- Python **3.8+**
- [smartmontools](https://www.smartmontools.org/) (`smartctl`)
- администраторски / root права (без тях SMART често е недостъпен)

### Инсталация на smartctl

**Debian / Ubuntu / Mint**
```bash
sudo apt install smartmontools python3
```

**Fedora / RHEL**
```bash
sudo dnf install smartmontools python3
```

**Arch**
```bash
sudo pacman -S smartmontools python
```

**macOS**
```bash
brew install smartmontools
```

**Windows**  
Свали инсталатора от [smartmontools.org/wiki/Download](https://www.smartmontools.org/wiki/Download).  
Пусни командния ред **като Администратор**.

Няма външни Python пакети — ползва се само стандартната библиотека.

---

## Инсталация

```bash
git clone https://github.com/<ПОТРЕБИТЕЛ>/ssd-health.git
cd ssd-health
chmod +x ssd_health.py
```

Копирай скрипта в домашната папка, ако ще ползваш десктоп икона:

```bash
cp ssd_health.py "$HOME/ssd_health.py"
```

---

## Употреба

### Linux / macOS

```bash
sudo python3 ssd_health.py
```

### Windows (Admin CMD / PowerShell)

```text
python ssd_health.py
```

### Опции

| Опция | Описание |
|---|---|
| *(без аргументи)* | еднократно извеждане |
| `-w 10` / `--watch 10` | опресняване на всеки 10 секунди |
| `-j` / `--json` | суров JSON (за скриптове и дебъг) |

Примери:

```bash
sudo python3 ssd_health.py -w 15
sudo python3 ssd_health.py -j
```

---

## Десктоп икона (Linux)

1. Сложи `ssd_health.py` в `$HOME`.
2. Създай стартов скрипт и `.desktop` файл:

```bash
cat > "$HOME/ssd_health_launch.sh" << 'EOF'
#!/bin/bash
SCRIPT="$HOME/ssd_health.py"
if [ ! -f "$SCRIPT" ]; then
  echo "Липсва $SCRIPT"
  read -r -p "Натисни Enter..."
  exit 1
fi
sudo python3 "$SCRIPT"
echo
read -r -p "Натисни Enter за затваряне..."
EOF

chmod +x "$HOME/ssd_health_launch.sh"

mkdir -p "$HOME/.local/share/applications"

cat > "$HOME/.local/share/applications/ssd-health.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Здраве на SSD
Comment=Показва SMART здравето на дисковете
Exec=$HOME/ssd_health_launch.sh
Icon=drive-harddisk
Terminal=true
Categories=Utility;System;
StartupNotify=true
EOF

chmod +x "$HOME/.local/share/applications/ssd-health.desktop"
cp "$HOME/.local/share/applications/ssd-health.desktop" "$HOME/Desktop/"
chmod +x "$HOME/Desktop/ssd-health.desktop"
gio set "$HOME/Desktop/ssd-health.desktop" metadata::trusted true 2>/dev/null || true
```

На иконата на плота: десен бутон → **Allow Launching** / **Разреши стартиране**.

Ще се отвори терминал, ще поиска `sudo` парола и ще изчака Enter преди да се затвори.

---

## Файлове

```
ssd_health.py           # основна програма
ssd_health_launch.sh    # стартер за десктоп иконата
ssd-health.desktop      # пример за .desktop файл
README.md
```

---

## Откриване на дискове

Скриптът вика `smartctl --scan-open`. Ако дискът се яви като SCSI, допълнително пробва SAT pass-through (`-d sat`), за да вземе пълните ATA SMART атрибути на SATA SSD.

Типични имена:

- Linux SATA: `/dev/sda`, `/dev/sdb`, …
- Linux NVMe: `/dev/nvme0n1`
- Windows: `/dev/sda` през smartctl, или `PhysicalDrive0`

USB кутии често **не** предават SMART. Тогава данните ще са частични или липсващи — това е ограничение на адаптера, не на скрипта.

---

## Пример за изход

```
╔══════════════════════════════════════════════════════════════╗
║           Здраве на дисковете  (SMART)                       ║
╚══════════════════════════════════════════════════════════════╝

  [1/1]  Samsung SSD 870 EVO 1TB  (SSD, SAT)
  Устройство           /dev/sda
  Сериен №             S6PTxxxxxxxxxxxx
  SMART статус         PASSED
  Оценка здраве        97%   ОТЛИЧНО
  Температура          34 °C
  Работни часове       11,284 ч  (~1.3 год.)
  Оставащ ресурс       92%   (износено 8%)
```

---

## Чести проблеми

| Симптом | Причина / решение |
|---|---|
| `Трябват root права` | Пусни с `sudo python3 ssd_health.py` |
| `Не е намерен smartctl` | Инсталирай `smartmontools` и отвори нов терминал |
| Няма открити дискове | Липсва sudo / дискът е зад USB мост или RAID контролер |
| `No such device` за `/dev/nvme0n1` | Нямаш NVMe — нормално, гледай `/dev/sda` |
| Десктоп иконата: *did not specify Exec field* | `.desktop` файлът е счупен; създай го с командите по-горе, не с ръчно копиране на кавички |
| Иконата на плота не тръгва | Allow Launching + `chmod +x` |

Проверка, че `smartctl` изобщо вижда диска:

```bash
sudo smartctl --scan
sudo smartctl -H /dev/sda
```

---

## Сигурност

Скриптът **само чете** SMART. Не форматира, не пише по диска и не пуска дълги самотестове, освен ако не ги добавиш сам чрез `smartctl`.

`sudo` е нужен, защото ядрото не дава SMART на обикновен потребител.

---

## Лиценз

MIT. Ползвай, променяй, споделяй.

SMART данните и оценката са информативни. Авторът не носи отговорност при загуба на данни — дръж резервни копия.
