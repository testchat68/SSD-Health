#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ssd_health.py — показва здравето на SSD/HDD чрез SMART данни.

Изисквания:
  1. Python 3.8+
  2. smartmontools (командата smartctl)

Инсталация на smartctl:
  Linux:   sudo apt install smartmontools
           sudo dnf install smartmontools
  Windows: https://www.smartmontools.org/wiki/Download
           (инсталирай и пусни този скрипт като Администратор)
  macOS:   brew install smartmontools

Пускане:
  Linux/macOS:  sudo python3 ssd_health.py
  Windows:      python ssd_health.py   (от командния ред като Администратор)

Опции:
  python3 ssd_health.py          # еднократно
  python3 ssd_health.py -w 10    # опресняване на всеки 10 секунди
  python3 ssd_health.py -j       # суров JSON за дебъг
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any, Optional


# ── цветове (изключват се ако изходът не е терминал) ─────────────────────────
def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass
    return sys.stdout.isatty()


USE_COLOR = _supports_color()


class C:
    R = "\033[0m" if USE_COLOR else ""
    B = "\033[1m" if USE_COLOR else ""
    DIM = "\033[2m" if USE_COLOR else ""
    RED = "\033[91m" if USE_COLOR else ""
    GRN = "\033[92m" if USE_COLOR else ""
    YEL = "\033[93m" if USE_COLOR else ""
    BLU = "\033[94m" if USE_COLOR else ""
    MAG = "\033[95m" if USE_COLOR else ""
    CYN = "\033[96m" if USE_COLOR else ""
    WHT = "\033[97m" if USE_COLOR else ""


def color_health(pct: Optional[float]) -> str:
    if pct is None:
        return C.DIM + "н/д" + C.R
    if pct >= 90:
        col = C.GRN
    elif pct >= 70:
        col = C.YEL
    else:
        col = C.RED
    return f"{col}{C.B}{pct:.0f}%{C.R}"


def color_temp(t: Optional[float]) -> str:
    if t is None:
        return C.DIM + "н/д" + C.R
    if t < 50:
        col = C.GRN
    elif t < 65:
        col = C.YEL
    else:
        col = C.RED
    return f"{col}{t:.0f} °C{C.R}"


def color_ok(ok: Optional[bool], yes="PASSED", no="FAILED") -> str:
    if ok is None:
        return C.DIM + "н/д" + C.R
    return (C.GRN + C.B + yes + C.R) if ok else (C.RED + C.B + no + C.R)


def human_bytes(n: Optional[int]) -> str:
    if n is None:
        return "н/д"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    x = float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            if u in ("B", "KB"):
                return f"{x:.0f} {u}"
            return f"{x:.2f} {u}"
        x /= 1024
    return f"{n}"


def human_hours(h: Optional[int]) -> str:
    if h is None:
        return "н/д"
    days = h / 24
    years = days / 365.25
    if years >= 1:
        return f"{h:,} ч  (~{years:.1f} год.)"
    return f"{h:,} ч  (~{days:.0f} дни)"


def find_smartctl() -> Optional[str]:
    p = shutil.which("smartctl")
    if p:
        return p
    extra = []
    if sys.platform == "win32":
        extra = [
            r"C:\Program Files\smartmontools\bin\smartctl.exe",
            r"C:\Program Files (x86)\smartmontools\bin\smartctl.exe",
        ]
    else:
        extra = ["/usr/sbin/smartctl", "/usr/local/sbin/smartctl", "/opt/homebrew/sbin/smartctl"]
    for c in extra:
        if os.path.isfile(c):
            return c
    return None


def run_smartctl(smartctl: str, args: list[str]) -> tuple[int, str]:
    cmd = [smartctl] + args
    # На Linux често трябва sudo; ако вече сме root, не го добавяме.
    if sys.platform != "win32" and os.geteuid() != 0:
        if shutil.which("sudo"):
            cmd = ["sudo", "-n"] + cmd
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=40,
        )
        out = r.stdout or ""
        if r.returncode != 0 and not out.strip():
            out = r.stderr or ""
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return 124, ""
    except FileNotFoundError:
        return 127, ""


def parse_json(text: str) -> Optional[dict]:
    text = text.strip()
    if not text:
        return None
    # понякога sudo печата предупреждение преди JSON
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None


def scan_devices(smartctl: str) -> list[dict]:
    code, out = run_smartctl(smartctl, ["--scan-open", "--json"])
    data = parse_json(out)
    devices = []
    if data and "devices" in data:
        for d in data["devices"]:
            name = d.get("name")
            if not name:
                continue
            devices.append({
                "name": name,
                "type": d.get("type"),
                "info_name": d.get("info_name", name),
                "protocol": d.get("protocol"),
            })
    if devices:
        return devices

    # резервен план: ръчно търсене
    candidates = []
    if sys.platform == "win32":
        for i in range(8):
            candidates.append(f"/dev/pd{i}")
            candidates.append(f"/dev/sd" + chr(ord("a") + i))
    else:
        for letter in "abcdefghij":
            candidates.append(f"/dev/sd{letter}")
        for i in range(4):
            candidates.append(f"/dev/nvme{i}n1")
            candidates.append(f"/dev/nvme{i}")
    seen = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        code, out = run_smartctl(smartctl, ["-i", "--json", c])
        data = parse_json(out)
        if data and data.get("model_name") or data.get("device"):
            devices.append({"name": c, "type": None, "info_name": c, "protocol": None})
    return devices


def attr_raw(ata_attrs: list, *ids_or_names) -> Optional[int]:
    want_ids = {x for x in ids_or_names if isinstance(x, int)}
    want_names = {str(x).lower() for x in ids_or_names if isinstance(x, str)}
    for a in ata_attrs or []:
        aid = a.get("id")
        name = (a.get("name") or "").lower()
        if aid in want_ids or name in want_names:
            raw = a.get("raw", {})
            if isinstance(raw, dict) and "value" in raw:
                return raw["value"]
            if "raw" in a and isinstance(a["raw"], (int, float)):
                return int(a["raw"])
    return None


def attr_value(ata_attrs: list, *ids_or_names) -> Optional[int]:
    """Нормализираната VALUE колона (0-100+), полезна за Wear_Leveling_Count."""
    want_ids = {x for x in ids_or_names if isinstance(x, int)}
    want_names = {str(x).lower() for x in ids_or_names if isinstance(x, str)}
    for a in ata_attrs or []:
        aid = a.get("id")
        name = (a.get("name") or "").lower()
        if aid in want_ids or name in want_names:
            v = a.get("value")
            if isinstance(v, (int, float)):
                return int(v)
    return None


def collect_drive(smartctl: str, dev: dict) -> dict:
    name = dev["name"]
    extra = []
    if dev.get("type"):
        extra = ["-d", str(dev["type"])]
    code, out = run_smartctl(smartctl, extra + ["-a", "--json", name])
    data = parse_json(out) or {}

    model = data.get("model_name") or data.get("scsi_model_name") or "неизвестно"
    serial = data.get("serial_number") or "н/д"
    fw = data.get("firmware_version") or data.get("scsi_revision") or "н/д"
    proto = (data.get("device") or {}).get("protocol") or dev.get("protocol") or "н/д"
    rotation = data.get("rotation_rate")
    is_ssd = rotation == 0 or (isinstance(proto, str) and proto.lower() == "nvme")
    if data.get("nvme_smart_health_information_log") is not None:
        is_ssd = True

    capacity = None
    if "user_capacity" in data and isinstance(data["user_capacity"], dict):
        capacity = data["user_capacity"].get("bytes")
    elif "nvme_total_capacity" in data:
        capacity = data["nvme_total_capacity"]

    smart_ok = None
    st = data.get("smart_status")
    if isinstance(st, dict) and "passed" in st:
        smart_ok = bool(st["passed"])

    temp = None
    t = data.get("temperature")
    if isinstance(t, dict):
        temp = t.get("current")
    nvme = data.get("nvme_smart_health_information_log") or {}
    if temp is None and "temperature" in nvme:
        temp = nvme.get("temperature")

    power_on = None
    pot = data.get("power_on_time")
    if isinstance(pot, dict):
        power_on = pot.get("hours")
    if power_on is None:
        power_on = nvme.get("power_on_hours")

    power_cycles = data.get("power_cycle_count") or nvme.get("power_cycles")

    ata = data.get("ata_smart_attributes", {}).get("table", []) if isinstance(data.get("ata_smart_attributes"), dict) else []

    if power_on is None:
        power_on = attr_raw(ata, 9, "Power_On_Hours")
    if power_cycles is None:
        power_cycles = attr_raw(ata, 12, "Power_Cycle_Count")
    if temp is None:
        temp = attr_raw(ata, 194, 190, "Temperature_Celsius", "Airflow_Temperature_Cel")
        # някои дискове кодират температурата в младшите байтове
        if isinstance(temp, int) and temp > 200:
            temp = temp & 0xFF

    realloc = attr_raw(ata, 5, "Reallocated_Sector_Ct", "Reallocated_Sector_Count")
    pending = attr_raw(ata, 197, "Current_Pending_Sector")
    uncorr = attr_raw(ata, 198, "Offline_Uncorrectable")
    crc = attr_raw(ata, 199, "UDMA_CRC_Error_Count", "CRC_Error_Count")

    # износване / оставащ живот
    pct_used = nvme.get("percentage_used")  # NVMe: 0-100+ използвано
    wear_left = None  # 100 = ново
    if pct_used is not None:
        wear_left = max(0, 100 - int(pct_used))
    else:
        # SATA SSD: Wear_Leveling_Count / Percent_Lifetime_Remain / SSD_Life_Left
        # VALUE обикновено започва от 100 и намалява
        for aid, nname in (
            (177, "Wear_Leveling_Count"),
            (202, "Percent_Lifetime_Remain"),
            (231, "SSD_Life_Left"),
            (233, "Media_Wearout_Indicator"),
            (169, "Remaining_Lifetime_Perc"),
        ):
            v = attr_value(ata, aid, nname)
            if v is not None:
                wear_left = v
                pct_used = max(0, 100 - v)
                break

    spare = nvme.get("available_spare")
    spare_th = nvme.get("available_spare_threshold")
    media_err = nvme.get("media_errors")
    unsafe = nvme.get("unsafe_shutdowns")
    crit_warn = nvme.get("critical_warning")

    # TBW: NVMe data_units_written * 512000 bytes
    tb_written = None
    tb_read = None
    if "data_units_written" in nvme:
        tb_written = nvme["data_units_written"] * 512_000
    if "data_units_read" in nvme:
        tb_read = nvme["data_units_read"] * 512_000
    # SATA: Total_LBAs_Written (id 241) * 512
    lba_w = attr_raw(ata, 241, "Total_LBAs_Written")
    lba_r = attr_raw(ata, 242, "Total_LBAs_Read")
    if tb_written is None and lba_w is not None:
        tb_written = lba_w * 512
    if tb_read is None and lba_r is not None:
        tb_read = lba_r * 512

    # оценка на здравето 0-100
    health = 100.0
    notes = []
    if smart_ok is False:
        health = min(health, 10)
        notes.append("SMART самооценката е FAILED — архивирай веднага")
    if crit_warn:
        health = min(health, 25)
        notes.append(f"NVMe critical warning = {crit_warn}")
    if wear_left is not None:
        health = min(health, float(wear_left))
        if wear_left < 10:
            notes.append("много високо износване на NAND")
        elif wear_left < 20:
            notes.append("износването наближава края на ресурса")
    if spare is not None:
        if spare_th is not None and spare <= spare_th:
            health = min(health, 20)
            notes.append("резервните блокове са под прага")
        elif spare < 50:
            health = min(health, 50 + spare / 2)
            notes.append(f"намален резерв ({spare}%)")
    if realloc and realloc > 0:
        penalty = min(40, realloc * 5)
        health -= penalty
        notes.append(f"преразпределени сектори: {realloc}")
    if pending and pending > 0:
        health -= min(30, pending * 5)
        notes.append(f"чакащи сектори: {pending}")
    if uncorr and uncorr > 0:
        health -= min(30, uncorr * 5)
        notes.append(f"непоправими сектори: {uncorr}")
    if media_err and media_err > 0:
        health -= min(40, media_err * 10)
        notes.append(f"медийни грешки: {media_err}")
    if temp is not None and temp >= 70:
        health -= 10
        notes.append(f"висока температура ({temp} °C)")
    health = max(0.0, min(100.0, health))

    if smart_ok is False:
        verdict = "КРИТИЧНО"
    elif health >= 90 and not notes:
        verdict = "ОТЛИЧНО"
    elif health >= 75:
        verdict = "ДОБРО"
    elif health >= 50:
        verdict = "ВНИМАНИЕ"
    else:
        verdict = "ЛОШО"

    return {
        "name": name,
        "model": model,
        "serial": serial,
        "firmware": fw,
        "protocol": proto,
        "is_ssd": is_ssd,
        "capacity": capacity,
        "smart_ok": smart_ok,
        "health": health,
        "verdict": verdict,
        "temp": temp,
        "power_on": power_on,
        "power_cycles": power_cycles,
        "pct_used": pct_used,
        "wear_left": wear_left,
        "spare": spare,
        "spare_th": spare_th,
        "realloc": realloc,
        "pending": pending,
        "uncorr": uncorr,
        "crc": crc,
        "media_err": media_err,
        "unsafe": unsafe,
        "tb_written": tb_written,
        "tb_read": tb_read,
        "notes": notes,
        "raw_exit": code,
        "has_data": bool(data.get("model_name") or nvme or ata),
    }


def print_drive(d: dict, idx: int, total: int) -> None:
    kind = "SSD" if d["is_ssd"] else "HDD"
    line = "─" * 64
    print(f"\n{C.CYN}{line}{C.R}")
    print(f"{C.B}{C.WHT}  [{idx}/{total}]  {d['model']}{C.R}  {C.DIM}({kind}, {d['protocol']}){C.R}")
    print(f"{C.CYN}{line}{C.R}")

    if not d["has_data"]:
        print(f"  {C.YEL}Няма SMART данни. Пусни скрипта с администраторски права.{C.R}")
        print(f"  устройство: {d['name']}")
        return

    vcol = {
        "ОТЛИЧНО": C.GRN,
        "ДОБРО": C.GRN,
        "ВНИМАНИЕ": C.YEL,
        "ЛОШО": C.RED,
        "КРИТИЧНО": C.RED,
    }.get(d["verdict"], C.WHT)

    rows = [
        ("Устройство", d["name"]),
        ("Сериен №", d["serial"]),
        ("Фирмуер", d["firmware"]),
        ("Капацитет", human_bytes(d["capacity"])),
        ("SMART статус", color_ok(d["smart_ok"])),
        ("Оценка здраве", f"{color_health(d['health'])}   {vcol}{C.B}{d['verdict']}{C.R}"),
        ("Температура", color_temp(d["temp"])),
        ("Работни часове", human_hours(d["power_on"])),
        ("Включвания", f"{d['power_cycles']:,}" if d["power_cycles"] is not None else "н/д"),
    ]
    if d["wear_left"] is not None or d["pct_used"] is not None:
        left = d["wear_left"]
        used = d["pct_used"]
        extra = ""
        if used is not None:
            extra = f"   (износено {used}%)"
        rows.append(("Оставащ ресурс", f"{color_health(left if left is not None else None)}{extra}"))
    if d["spare"] is not None:
        th = f"  (праг {d['spare_th']}%)" if d["spare_th"] is not None else ""
        rows.append(("Резервни блокове", f"{d['spare']}%{th}"))
    if d["tb_written"] is not None:
        rows.append(("Записани данни", human_bytes(d["tb_written"])))
    if d["tb_read"] is not None:
        rows.append(("Прочетени данни", human_bytes(d["tb_read"])))
    if d["realloc"] is not None:
        rows.append(("Преразпред. сектори", str(d["realloc"])))
    if d["pending"] is not None:
        rows.append(("Чакащи сектори", str(d["pending"])))
    if d["uncorr"] is not None:
        rows.append(("Непоправими сектори", str(d["uncorr"])))
    if d["media_err"] is not None:
        rows.append(("Медийни грешки", str(d["media_err"])))
    if d["unsafe"] is not None:
        rows.append(("Небезопасни спирания", str(d["unsafe"])))
    if d["crc"] is not None:
        rows.append(("CRC грешки", str(d["crc"])))

    w = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"  {C.DIM}{k:<{w}}{C.R}  {v}")

    if d["notes"]:
        print(f"\n  {C.YEL}{C.B}Забележки:{C.R}")
        for n in d["notes"]:
            print(f"    • {n}")


def print_header() -> None:
    print(f"{C.B}{C.CYN}╔══════════════════════════════════════════════════════════════╗{C.R}")
    print(f"{C.B}{C.CYN}║           Здраве на дисковете  (SMART)                       ║{C.R}")
    print(f"{C.B}{C.CYN}╚══════════════════════════════════════════════════════════════╝{C.R}")
    print(f"{C.DIM}  {platform.system()} {platform.release()}   {time.strftime('%Y-%m-%d %H:%M:%S')}{C.R}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Показва здравето на SSD/HDD чрез SMART.")
    ap.add_argument("-w", "--watch", type=int, metavar="SEC", help="опресняване на всеки N секунди")
    ap.add_argument("-j", "--json", action="store_true", help="изведи JSON вместо текст")
    args = ap.parse_args()

    smartctl = find_smartctl()
    if not smartctl:
        print(f"{C.RED}Не е намерен smartctl.{C.R}")
        print()
        print("Инсталирай smartmontools:")
        print("  Linux:    sudo apt install smartmontools")
        print("  Windows:  https://www.smartmontools.org/wiki/Download")
        print("  macOS:    brew install smartmontools")
        return 2

    def once() -> list[dict]:
        devs = scan_devices(smartctl)
        results = [collect_drive(smartctl, d) for d in devs]
        return results

    if args.watch:
        try:
            while True:
                if sys.platform != "win32":
                    os.system("clear")
                else:
                    os.system("cls")
                print_header()
                results = once()
                if not results:
                    print(f"\n  {C.YEL}Няма открити дискове. Пусни като администратор/root.{C.R}")
                else:
                    for i, d in enumerate(results, 1):
                        print_drive(d, i, len(results))
                print(f"\n{C.DIM}  Опресняване след {args.watch} сек.  Ctrl+C за изход.{C.R}")
                time.sleep(max(3, args.watch))
        except KeyboardInterrupt:
            print("\nСпряно.")
            return 0

    results = once()
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return 0

    print_header()
    if not results:
        print(f"\n  {C.YEL}Няма открити дискове.{C.R}")
        print("  Linux:   sudo python3 ssd_health.py")
        print("  Windows: стартирай командния ред като Администратор")
        return 1

    for i, d in enumerate(results, 1):
        print_drive(d, i, len(results))

    print()
    print(f"{C.DIM}  Оценка ≥90% = отлично, 75–89 = добре, 50–74 = внимание, <50 = риск.{C.R}")
    print(f"{C.DIM}  SMART не гарантира бъдещето — прави резервни копия.{C.R}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
