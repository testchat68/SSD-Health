#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ssd_health.py — SSD/HDD health via SMART (smartmontools).

Run:   sudo python3 ssd_health.py
       sudo python3 ssd_health.py -d /dev/sda --lang bg
       sudo python3 ssd_health.py --check        # exit code for cron/scripts

Exit codes:
    0  all drives OK (EXCELLENT / GOOD)
    1  at least one drive CAUTION      (only with --check)
    2  at least one drive POOR/CRITICAL (only with --check)
    10 smartctl not found
    11 no drives found
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Optional

# ───────────────────────────── colours ─────────────────────────────


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


class C:
    R = B = DIM = RED = GRN = YEL = CYN = WHT = PUR = ORG = SGR = ""


_CODES = {
    "R": "\033[0m", "B": "\033[1m", "DIM": "\033[2m",
    "RED": "\033[91m", "GRN": "\033[92m", "YEL": "\033[93m",
    "CYN": "\033[96m", "WHT": "\033[97m",
    # theme: purple labels, orange values, frames in the same bold bright green as PASSED
    "PUR": "\033[38;5;141m", "ORG": "\033[38;5;215m", "SGR": "\033[1m\033[92m",
}


def set_color(on: bool) -> None:
    for k, v in _CODES.items():
        setattr(C, k, v if on else "")


UNICODE_OK = True


def _can_encode(text: str) -> bool:
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def setup_output() -> None:
    """Never crash on consoles that are not UTF-8 (Windows cmd, pipes, SSH)."""
    global UNICODE_OK
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    UNICODE_OK = _can_encode("╔═╗║─•°")


def g(unicode_s: str, ascii_s: str) -> str:
    return unicode_s if UNICODE_OK else ascii_s


# ───────────────────────────── i18n ────────────────────────────────

LANG = "en"

STR = {
    "en": {
        "title": "Drive health  (SMART)",
        "device": "Device", "serial": "Serial", "firmware": "Firmware",
        "capacity": "Capacity", "smart": "SMART status",
        "score": "Health score", "temp": "Temperature",
        "poh": "Power-on hours", "cycles": "Power cycles",
        "pue": "Percentage Used Endurance", "used": "used",
        "remaining": "remaining", "life": "Remaining life",
        "ee": "EE Cycles Remaining", "spare": "Available spare",
        "written": "Data written", "read": "Data read",
        "perday": "Avg. written / day",
        "realloc": "Reallocated sectors", "pending": "Pending sectors",
        "uncorr": "Uncorrectable sectors", "mediaerr": "Media errors",
        "unsafe": "Unsafe shutdowns", "crc": "CRC errors",
        "notes": "Notes:", "threshold": "threshold",
        "no_data": "No SMART data. Run the script as administrator/root.",
        "no_drives": "No drives found. Run as administrator/root.",
        "more": "More detail — copy/paste into a terminal:",
        "refresh": "Refreshing in {n} s.  Ctrl+C to exit.",
        "stopped": "Stopped.",
        "no_smartctl": "smartctl not found.",
        "install": "Install:  sudo apt install smartmontools   (Windows: https://www.smartmontools.org)",
        "not_root": "Not running as administrator/root — results may be incomplete.",
        "EXCELLENT": "EXCELLENT", "GOOD": "GOOD", "CAUTION": "CAUTION",
        "POOR": "POOR", "CRITICAL": "CRITICAL",
        "yes": "PASSED", "no": "FAILED",
        "n_failed": "SMART overall-health is FAILED — back up immediately",
        "n_crit": "NVMe critical warning = {v}",
        "n_wear_hi": "NAND wear is very high",
        "n_wear_mid": "wear is approaching end of rated life",
        "n_pue90": "Percentage Used Endurance = {v}%",
        "n_pue80": "Device Statistics wear is high ({v}% used)",
        "n_spare_th": "available spare is at or below threshold",
        "n_spare_low": "reduced spare blocks ({v}%)",
        "n_realloc": "reallocated sectors: {v}",
        "n_pending": "pending sectors: {v}",
        "n_uncorr": "uncorrectable sectors: {v}",
        "n_media": "media errors: {v}",
        "n_temp": "high temperature ({v} °C)",
        "n_crc": "CRC errors: {v} (usually a bad cable/connector, not the drive)",
        "n_two": "two counters: Device Statistics {a}% used "
                 "(remaining {b}%), attribute remaining {c}%",
        "days": "days", "yr": "yr",
    },
    "bg": {
        "title": "Здраве на дисковете  (SMART)",
        "device": "Устройство", "serial": "Сериен №", "firmware": "Фърмуер",
        "capacity": "Капацитет", "smart": "SMART статус",
        "score": "Оценка на здравето", "temp": "Температура",
        "poh": "Часове на работа", "cycles": "Включвания",
        "pue": "Използван ресурс (Endurance)", "used": "използвано",
        "remaining": "остава", "life": "Оставащ живот",
        "ee": "EE оставащи цикли", "spare": "Резервни блокове",
        "written": "Записани данни", "read": "Прочетени данни",
        "perday": "Средно записани / ден",
        "realloc": "Реалокирани сектори", "pending": "Чакащи сектори",
        "uncorr": "Некоригируеми сектори", "mediaerr": "Грешки в носителя",
        "unsafe": "Неправилни изключвания", "crc": "CRC грешки",
        "notes": "Бележки:", "threshold": "праг",
        "no_data": "Няма SMART данни. Стартирай като администратор/root.",
        "no_drives": "Не са намерени дискове. Стартирай като администратор/root.",
        "more": "Повече подробности — копирай в терминал:",
        "refresh": "Обновяване след {n} с.  Ctrl+C за изход.",
        "stopped": "Спряно.",
        "no_smartctl": "smartctl не е намерен.",
        "install": "Инсталиране:  sudo apt install smartmontools   (Windows: https://www.smartmontools.org)",
        "not_root": "Не е стартирано като администратор/root — резултатите може да са непълни.",
        "EXCELLENT": "ОТЛИЧНО", "GOOD": "ДОБРО", "CAUTION": "ВНИМАНИЕ",
        "POOR": "ЛОШО", "CRITICAL": "КРИТИЧНО",
        "yes": "ОК", "no": "ПРОВАЛ",
        "n_failed": "SMART общото състояние е FAILED — веднага направи резервно копие",
        "n_crit": "NVMe критично предупреждение = {v}",
        "n_wear_hi": "Износването на NAND е много високо",
        "n_wear_mid": "износването наближава края на заявения живот",
        "n_pue90": "Използван ресурс (Endurance) = {v}%",
        "n_pue80": "Износването по Device Statistics е високо ({v}% използвано)",
        "n_spare_th": "резервните блокове са на или под прага",
        "n_spare_low": "намалени резервни блокове ({v}%)",
        "n_realloc": "реалокирани сектори: {v}",
        "n_pending": "чакащи сектори: {v}",
        "n_uncorr": "некоригируеми сектори: {v}",
        "n_media": "грешки в носителя: {v}",
        "n_temp": "висока температура ({v} °C)",
        "n_crc": "CRC грешки: {v} (обикновено лош кабел/конектор, не самият диск)",
        "n_two": "два брояча: Device Statistics {a}% използвано "
                 "(остава {b}%), атрибут – остава {c}%",
        "days": "дни", "yr": "год.",
    },
}


def t(key: str, **kw) -> str:
    s = STR.get(LANG, STR["en"]).get(key) or STR["en"][key]
    s = s.format(**kw) if kw else s
    if not UNICODE_OK:
        s = s.replace("°C", "C").replace("—", "-")
    return s


# ───────────────────────────── formatting ──────────────────────────


def color_health(pct: Optional[float]) -> str:
    if pct is None:
        return C.DIM + "n/a" + C.R
    col = C.GRN if pct >= 90 else C.YEL if pct >= 70 else C.RED
    return f"{col}{C.B}{pct:.0f}%{C.R}"


def color_used(pct: Optional[float]) -> str:
    if pct is None:
        return C.DIM + "n/a" + C.R
    col = C.GRN if pct <= 10 else C.YEL if pct <= 30 else C.RED
    return f"{col}{C.B}{pct:.0f}%{C.R}"


def color_temp(v: Optional[float]) -> str:
    if v is None:
        return C.DIM + "n/a" + C.R
    col = C.GRN if v < 50 else C.YEL if v < 65 else C.RED
    return f"{col}{v:.0f} {g('°C', 'C')}{C.R}"


def color_ok(ok: Optional[bool]) -> str:
    if ok is None:
        return C.DIM + "n/a" + C.R
    return (C.GRN + C.B + t("yes") + C.R) if ok else (C.RED + C.B + t("no") + C.R)


def human_bytes(n: Optional[float]) -> str:
    if n is None:
        return "n/a"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    x = float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.0f} {u}" if u in ("B", "KB") else f"{x:.2f} {u}"
        x /= 1024
    return str(n)


def human_hours(h: Optional[int]) -> str:
    if h is None:
        return "n/a"
    days = h / 24
    years = days / 365.25
    if years >= 1:
        return f"{h:,} h  (~{years:.1f} {t('yr')})"
    return f"{h:,} h  (~{days:.0f} {t('days')})"


# ───────────────────────────── smartctl ────────────────────────────


def is_admin() -> bool:
    if sys.platform == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def find_smartctl() -> Optional[str]:
    p = shutil.which("smartctl")
    if p:
        return p
    if sys.platform == "win32":
        extra = [
            r"C:\Program Files\smartmontools\bin\smartctl.exe",
            r"C:\Program Files (x86)\smartmontools\bin\smartctl.exe",
        ]
    else:
        extra = ["/usr/sbin/smartctl", "/usr/local/sbin/smartctl",
                 "/opt/homebrew/sbin/smartctl"]
    for c in extra:
        if os.path.isfile(c):
            return c
    return None


def run_smartctl(smartctl: str, args: list[str]) -> tuple[int, str]:
    cmd = [smartctl] + args
    if sys.platform != "win32" and os.geteuid() != 0 and shutil.which("sudo"):
        cmd = ["sudo", "-n"] + cmd
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
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
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None


def scan_devices(smartctl: str) -> list[dict]:
    _code, out = run_smartctl(smartctl, ["--scan-open", "--json"])
    data = parse_json(out)
    devices: list[dict] = []
    if data and "devices" in data:
        for d in data["devices"]:
            name = d.get("name")
            if name:
                devices.append({
                    "name": name,
                    "type": d.get("type"),
                    "info_name": d.get("info_name", name),
                    "protocol": d.get("protocol"),
                })
    if devices:
        return devices

    # Fallback: probe common device names.
    candidates: list[str] = []
    if sys.platform == "win32":
        candidates = ["/dev/sd" + chr(ord("a") + i) for i in range(8)]
    else:
        candidates = [f"/dev/sd{c}" for c in "abcdefghij"]
        for i in range(4):
            candidates.append(f"/dev/nvme{i}")
    for c in candidates:
        _code, out = run_smartctl(smartctl, ["-i", "--json", c])
        data = parse_json(out)
        # (fixed operator-precedence bug: `data` may be None)
        if data and (data.get("model_name") or data.get("scsi_model_name")):
            devices.append({"name": c, "type": None, "info_name": c, "protocol": None})
    return devices


# ───────────────────────────── attribute helpers ───────────────────


def find_attr(ata_attrs: list, *ids_or_names) -> Optional[dict]:
    want_ids = {x for x in ids_or_names if isinstance(x, int)}
    want_names = {str(x).lower() for x in ids_or_names if isinstance(x, str)}
    for a in ata_attrs or []:
        if a.get("id") in want_ids or (a.get("name") or "").lower() in want_names:
            return a
    return None


def attr_raw(ata_attrs: list, *ids_or_names) -> Optional[int]:
    a = find_attr(ata_attrs, *ids_or_names)
    if not a:
        return None
    raw = a.get("raw")
    if isinstance(raw, dict) and isinstance(raw.get("value"), (int, float)):
        return int(raw["value"])
    if isinstance(raw, (int, float)):
        return int(raw)
    return None


def attr_value(ata_attrs: list, *ids_or_names) -> Optional[int]:
    a = find_attr(ata_attrs, *ids_or_names)
    if not a:
        return None
    v = a.get("value")
    return int(v) if isinstance(v, (int, float)) else None


def attr_raw_string(ata_attrs: list, *ids_or_names) -> Optional[str]:
    a = find_attr(ata_attrs, *ids_or_names)
    if not a:
        return None
    raw = a.get("raw")
    if isinstance(raw, dict):
        if raw.get("string"):
            return str(raw["string"])
        if "value" in raw:
            return str(raw["value"])
    return str(raw) if raw is not None else None


def extract_pct_used_endurance(data: dict) -> Optional[int]:
    """SATA Device Statistics page 0x07: Percentage Used Endurance Indicator."""
    stats = data.get("ata_device_statistics") or {}
    for page in stats.get("pages") or []:
        table = page.get("table") or []
        for row in table:
            name = (row.get("name") or "").lower()
            if "percentage used endurance" in name or name == "percentage used":
                val = row.get("value")
                if isinstance(val, (int, float)):
                    return int(val)
        if "solid state" in (page.get("name") or "").lower():
            for row in table:
                if row.get("offset") in (8, 0x008):
                    val = row.get("value")
                    if isinstance(val, (int, float)):
                        return int(val)
    return None


# ───────────────────────────── collection ──────────────────────────


def collect_drive(smartctl: str, dev: dict) -> dict:
    name = dev["name"]
    extra = ["-d", str(dev["type"])] if dev.get("type") else []
    code, out = run_smartctl(smartctl, extra + ["-x", "--json", name])
    data = parse_json(out) or {}

    model = data.get("model_name") or data.get("scsi_model_name") or "unknown"
    serial = data.get("serial_number") or "n/a"
    fw = data.get("firmware_version") or data.get("scsi_revision") or "n/a"
    proto = (data.get("device") or {}).get("protocol") or dev.get("protocol") or "n/a"
    rotation = data.get("rotation_rate")
    nvme = data.get("nvme_smart_health_information_log") or {}
    is_ssd = (
        rotation == 0
        or (isinstance(proto, str) and proto.lower() == "nvme")
        or bool(nvme)
    )

    capacity = None
    if isinstance(data.get("user_capacity"), dict):
        capacity = data["user_capacity"].get("bytes")
    elif "nvme_total_capacity" in data:
        capacity = data["nvme_total_capacity"]

    smart_ok = None
    st = data.get("smart_status")
    if isinstance(st, dict) and "passed" in st:
        smart_ok = bool(st["passed"])

    temp = None
    tt = data.get("temperature")
    if isinstance(tt, dict):
        temp = tt.get("current")
    if temp is None and "temperature" in nvme:
        temp = nvme.get("temperature")

    ata_block = data.get("ata_smart_attributes")
    ata = ata_block.get("table", []) if isinstance(ata_block, dict) else []

    # Prefer SMART attribute 9. Device Statistics Power-on Hours is often wrong
    # on SanDisk X400 (776 vs 8797).
    power_on = attr_raw(ata, 9, "Power_On_Hours")
    if power_on is not None and power_on > 10_000_000:
        power_on &= 0xFFFFFF  # some drives pack minutes/ms in the high bytes
    if power_on is None:
        power_on = nvme.get("power_on_hours")
    if power_on is None:
        pot = data.get("power_on_time")
        if isinstance(pot, dict):
            power_on = pot.get("hours")

    power_cycles = attr_raw(ata, 12, "Power_Cycle_Count")
    if power_cycles is None:
        power_cycles = data.get("power_cycle_count") or nvme.get("power_cycles")

    if temp is None:
        temp = attr_raw(ata, 194, 190, "Temperature_Celsius", "Airflow_Temperature_Cel")
        if isinstance(temp, int) and temp > 150:
            temp &= 0xFF  # raw packs min/max in the upper bytes

    realloc = attr_raw(ata, 5, "Reallocated_Sector_Ct", "Reallocated_Sector_Count")
    pending = attr_raw(ata, 197, "Current_Pending_Sector")
    uncorr = attr_raw(ata, 198, "Offline_Uncorrectable")
    crc = attr_raw(ata, 199, "UDMA_CRC_Error_Count", "CRC_Error_Count")
    e6_value = attr_value(ata, 230)
    ee_value = attr_value(ata, 238)
    ee_raw = attr_raw(ata, 238)
    ee_raw_s = attr_raw_string(ata, 238)

    pct_used_endurance = extract_pct_used_endurance(data)

    # ── wear ──
    pct_used = nvme.get("percentage_used")
    wear_left = None
    wear_source = None
    if pct_used is not None:
        wear_left = max(0, 100 - int(pct_used))
        wear_source = "NVMe percentage_used"
    else:
        candidates = []
        if ee_value is not None:
            candidates.append((ee_value, "EE Media Wearout (Cycles Remaining)"))
        # (fixed: attr 230 is matched by ID only, otherwise its name would
        #  also match attribute 233 "Media_Wearout_Indicator")
        for ids, label in (
            ((177, "Wear_Leveling_Count"), "177 Wear_Leveling_Count"),
            ((202, "Percent_Lifetime_Remain"), "202 Percent_Lifetime_Remain"),
            ((231, "SSD_Life_Left"), "231 SSD_Life_Left"),
            ((233, "Media_Wearout_Indicator"), "233 Media_Wearout_Indicator"),
            ((169, "Remaining_Lifetime_Perc"), "169 Remaining_Lifetime_Perc"),
            ((230,), "E6 Media Wearout Indicator"),
        ):
            v = attr_value(ata, *ids)
            if v is None:
                continue
            if ids[0] in (230, 233) and ee_value is not None and ee_value < 100 and v >= 99:
                continue
            candidates.append((v, label))
        if candidates:
            wear_left, wear_source = candidates[0]
            pct_used = max(0, 100 - int(wear_left))

    spare = nvme.get("available_spare")
    spare_th = nvme.get("available_spare_threshold")
    media_err = nvme.get("media_errors")
    unsafe = nvme.get("unsafe_shutdowns")
    crit_warn = nvme.get("critical_warning")

    # NVMe data units are 1000 × 512-byte blocks.
    tb_written = nvme["data_units_written"] * 512_000 if "data_units_written" in nvme else None
    tb_read = nvme["data_units_read"] * 512_000 if "data_units_read" in nvme else None
    lba_w = attr_raw(ata, 241, "Total_LBAs_Written")
    lba_r = attr_raw(ata, 242, "Total_LBAs_Read")
    if tb_written is None and lba_w is not None:
        tb_written = lba_w * 512
    if tb_read is None and lba_r is not None:
        tb_read = lba_r * 512

    per_day = None
    if tb_written is not None and power_on:
        per_day = tb_written / (power_on / 24)

    # ── health score ──
    health = 100.0
    notes: list[str] = []
    if smart_ok is False:
        health = min(health, 10)
        notes.append(t("n_failed"))
    if crit_warn:
        health = min(health, 25)
        notes.append(t("n_crit", v=crit_warn))
    if wear_left is not None:
        health = min(health, float(wear_left))
        if wear_left < 10:
            notes.append(t("n_wear_hi"))
        elif wear_left < 20:
            notes.append(t("n_wear_mid"))
    if pct_used_endurance is not None:
        if pct_used_endurance >= 90:
            notes.append(t("n_pue90", v=pct_used_endurance))
        elif pct_used_endurance >= 80:
            notes.append(t("n_pue80", v=pct_used_endurance))
    if spare is not None:
        if spare_th is not None and spare <= spare_th:
            health = min(health, 20)
            notes.append(t("n_spare_th"))
        elif spare < 50:
            health = min(health, 50 + spare / 2)
            notes.append(t("n_spare_low", v=spare))
    if realloc and realloc > 0:
        health -= min(40, realloc * 5)
        notes.append(t("n_realloc", v=realloc))
    if pending and pending > 0:
        health -= min(30, pending * 5)
        notes.append(t("n_pending", v=pending))
    if uncorr and uncorr > 0:
        health -= min(30, uncorr * 5)
        notes.append(t("n_uncorr", v=uncorr))
    if media_err and media_err > 0:
        health -= min(40, media_err * 10)
        notes.append(t("n_media", v=media_err))
    if crc and crc > 0:
        notes.append(t("n_crc", v=crc))  # informational: does not lower score
    if temp is not None and temp >= 70:
        health -= 10
        notes.append(t("n_temp", v=temp))
    if (
        pct_used_endurance is not None
        and wear_left is not None
        and abs((100 - pct_used_endurance) - wear_left) >= 2
    ):
        notes.append(t("n_two", a=pct_used_endurance, b=100 - pct_used_endurance, c=wear_left))

    health = max(0.0, min(100.0, health))
    if smart_ok is False:
        verdict = "CRITICAL"
    elif health >= 90 and not [n for n in notes if n != t("n_crc", v=crc)]:
        verdict = "EXCELLENT"
    elif health >= 75:
        verdict = "GOOD"
    elif health >= 50:
        verdict = "CAUTION"
    else:
        verdict = "POOR"

    return {
        "name": name, "model": model, "serial": serial, "firmware": fw,
        "protocol": proto, "is_ssd": is_ssd, "capacity": capacity,
        "smart_ok": smart_ok, "health": health, "verdict": verdict,
        "temp": temp, "power_on": power_on, "power_cycles": power_cycles,
        "pct_used": pct_used, "pct_used_endurance": pct_used_endurance,
        "wear_left": wear_left, "wear_source": wear_source,
        "e6_value": e6_value, "ee_value": ee_value, "ee_raw": ee_raw,
        "ee_raw_s": ee_raw_s, "spare": spare, "spare_th": spare_th,
        "realloc": realloc, "pending": pending, "uncorr": uncorr, "crc": crc,
        "media_err": media_err, "unsafe": unsafe,
        "tb_written": tb_written, "tb_read": tb_read, "written_per_day": per_day,
        "notes": notes, "raw_exit": code,
        "has_data": bool(data.get("model_name") or data.get("scsi_model_name") or nvme or ata),
    }


def dedupe(results: list[dict]) -> list[dict]:
    seen, out = set(), []
    for d in results:
        key = (d["serial"], d["model"]) if d["serial"] != "n/a" else d["name"]
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


# ───────────────────────────── output ──────────────────────────────


def print_drive(d: dict, idx: int, total: int) -> None:
    kind = "SSD" if d["is_ssd"] else "HDD"
    line = g("─", "-") * 64
    print(f"\n{C.SGR}{line}{C.R}")
    print(f"{C.PUR}  [{idx}/{total}]{C.R}  {C.B}{C.WHT}{d['model']}{C.R}  {C.ORG}({kind}, {d['protocol']}){C.R}")
    print(f"{C.SGR}{line}{C.R}")
    if not d["has_data"]:
        print(f"  {C.ORG}{t('no_data')}{C.R}")
        print(f"  {t('device')}: {d['name']}")
        return

    vcol = {"EXCELLENT": C.GRN, "GOOD": C.GRN, "CAUTION": C.YEL,
            "POOR": C.RED, "CRITICAL": C.RED}.get(d["verdict"], C.WHT)
    rows = [
        (t("device"), d["name"]),
        (t("serial"), d["serial"]),
        (t("firmware"), d["firmware"]),
        (t("capacity"), human_bytes(d["capacity"])),
        (t("smart"), color_ok(d["smart_ok"])),
        (t("score"), f"{color_health(d['health'])}   {vcol}{C.B}{t(d['verdict'])}{C.R}"),
        (t("temp"), color_temp(d["temp"])),
        (t("poh"), human_hours(d["power_on"])),
        (t("cycles"), f"{d['power_cycles']:,}" if d["power_cycles"] is not None else "n/a"),
    ]
    if d.get("pct_used_endurance") is not None:
        used = d["pct_used_endurance"]
        left = max(0, 100 - int(used))
        rows.append((
            t("pue"),
            f"{color_used(used)}{C.ORG} {t('used')}, {t('remaining')} {C.R}{color_health(left)}"
            f"{C.ORG}   [SATA Device Statistics 0x07]{C.R}",
        ))
    if d["wear_left"] is not None or d["pct_used"] is not None:
        extra = f"{C.ORG}   ({t('used')} {d['pct_used']}%){C.R}" if d["pct_used"] is not None else ""
        src = f"{C.ORG}   [{d['wear_source']}]{C.R}" if d.get("wear_source") else ""
        rows.append((t("life"), f"{color_health(d['wear_left'])}{extra}{src}"))
    if d.get("ee_value") is not None or d.get("ee_raw") is not None:
        if d.get("ee_raw_s"):
            rawbit = f"{C.ORG}   raw={d['ee_raw_s']}{C.R}"
        elif d.get("ee_raw") is not None:
            rawbit = f"{C.ORG}   raw={d['ee_raw']}{C.R}"
        else:
            rawbit = ""
        val = color_health(d["ee_value"]) if d.get("ee_value") is not None else C.DIM + "n/a" + C.R
        rows.append((t("ee"), f"{val}{rawbit}"))
    if d["spare"] is not None:
        th = f"  ({t('threshold')} {d['spare_th']}%)" if d["spare_th"] is not None else ""
        rows.append((t("spare"), f"{d['spare']}%{th}"))
    if d["tb_written"] is not None:
        rows.append((t("written"), human_bytes(d["tb_written"])))
    if d["written_per_day"] is not None:
        rows.append((t("perday"), human_bytes(d["written_per_day"]) + " / day"))
    if d["tb_read"] is not None:
        rows.append((t("read"), human_bytes(d["tb_read"])))
    for key, label in (("realloc", "realloc"), ("pending", "pending"),
                       ("uncorr", "uncorr"), ("media_err", "mediaerr"),
                       ("unsafe", "unsafe"), ("crc", "crc")):
        if d[key] is not None:
            rows.append((t(label), str(d[key])))

    w = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"  {C.PUR}{k:<{w}}{C.R}  {C.ORG}{v}{C.R}")
    if d["notes"]:
        print(f"\n  {C.ORG}{C.B}{t('notes')}{C.R}")
        for n in d["notes"]:
            print(f"    {C.ORG}{g('•', '*')}{C.R} {C.WHT}{n}{C.R}")


def print_smartctl_commands(results: list[dict]) -> None:
    if not results:
        return
    print(f"\n{C.SGR}{g('─', '-') * 64}{C.R}")
    print(f"{C.B}{C.ORG}  {t('more')}{C.R}")
    print(f"{C.SGR}{g('─', '-') * 64}{C.R}")
    prefix = "" if sys.platform == "win32" else "sudo "
    for d in results:
        name = d.get("name") or "/dev/sda"
        for flag in ("-H", "-A", "-x"):
            print(f"  {C.PUR}{prefix}{C.SGR}smartctl{C.R} {C.ORG}{flag}{C.R} {C.WHT}{name}{C.R}")
        print()


def print_header() -> None:
    title = t("title")
    tl, tr, bl, br, h, v = (("╔", "╗", "╚", "╝", "═", "║") if UNICODE_OK
                            else ("+", "+", "+", "+", "=", "|"))
    print(f"{C.B}{C.SGR}{tl}{h * 62}{tr}{C.R}")
    print(f"{C.B}{C.SGR}{v}{C.PUR}  {title:<60}{C.SGR}{v}{C.R}")
    print(f"{C.B}{C.SGR}{bl}{h * 62}{br}{C.R}")
    print(f"{C.SGR}  {platform.system()} {platform.release()}   "
          f"{time.strftime('%Y-%m-%d %H:%M:%S')}{C.R}")
    if not is_admin():
        print(f"  {C.ORG}{t('not_root')}{C.R}")


# ───────────────────────────── terminal size ───────────────────────

WANT_COLS, WANT_ROWS = 90, 40


def resize_terminal(cols: int = WANT_COLS, rows: int = WANT_ROWS) -> None:
    """Ask the terminal to grow to at least cols x rows (never shrinks it)."""
    if not sys.stdout.isatty():
        return
    cur = shutil.get_terminal_size((cols, rows))
    if cur.columns >= cols and cur.lines >= rows:
        return
    want_c, want_r = max(cols, cur.columns), max(rows, cur.lines)
    try:
        if sys.platform == "win32":
            os.system(f"mode con: cols={want_c} lines={want_r} >nul 2>&1")
        else:
            sys.stdout.write(f"\033[8;{want_r};{want_c}t")  # xterm resize request
            sys.stdout.flush()
        time.sleep(0.3)  # give the terminal time to apply the new size
    except Exception:
        pass


def emit(text: str) -> None:
    """Print text; if it is taller than the terminal, show it in `less`
    so the top is never lost (some terminals ignore resize requests)."""
    rows = shutil.get_terminal_size((WANT_COLS, 24)).lines
    if (
        sys.stdout.isatty()
        and sys.platform != "win32"
        and text.count("\n") + 1 > rows
        and shutil.which("less")
    ):
        try:
            p = subprocess.Popen(["less", "-RFX"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8", errors="replace"))
            return
        except Exception:
            pass
    sys.stdout.write(text)
    sys.stdout.flush()


# ───────────────────────────── main ────────────────────────────────


def default_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v.lower().startswith("bg"):
            return "bg"
    return "en"


def exit_code_for(results: list[dict]) -> int:
    verdicts = {d["verdict"] for d in results if d["has_data"]}
    if verdicts & {"POOR", "CRITICAL"}:
        return 2
    if "CAUTION" in verdicts:
        return 1
    return 0


def main() -> int:
    global LANG
    ap = argparse.ArgumentParser(description="Show SSD/HDD health via SMART.")
    ap.add_argument("-w", "--watch", type=int, metavar="SEC", help="refresh every N seconds")
    ap.add_argument("-j", "--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("-d", "--device", action="append", metavar="DEV",
                    help="check only this device (repeatable), e.g. /dev/sda")
    ap.add_argument("--lang", choices=("en", "bg"), default=default_lang(),
                    help="output language (default: from $LANG)")
    ap.add_argument("--no-resize", action="store_true",
                    help="do not try to resize the terminal to 90x40")
    ap.add_argument("--no-color", action="store_true", help="disable colours")
    ap.add_argument("--color", action="store_true", help="force colours even when piped (e.g. | less -R)")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 for CAUTION, 2 for POOR/CRITICAL (for cron/monitoring)")
    args = ap.parse_args()

    setup_output()
    LANG = args.lang
    if LANG == "bg" and not _can_encode("Ж"):
        LANG = "en"  # console cannot display Cyrillic
    set_color(not args.no_color and not args.json and (args.color or _supports_color()))

    if not args.json and not args.no_resize:
        resize_terminal()

    smartctl = find_smartctl()
    if not smartctl:
        print(f"{C.RED}{t('no_smartctl')}{C.R}", file=sys.stderr)
        print(t("install"), file=sys.stderr)
        return 10

    def once() -> list[dict]:
        if args.device:
            devs = [{"name": n, "type": None, "info_name": n, "protocol": None}
                    for n in args.device]
        else:
            devs = scan_devices(smartctl)
        return dedupe([collect_drive(smartctl, d) for d in devs])

    def render(results: list[dict], commands: bool = True) -> None:
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
            return
        print_header()
        if not results:
            print(f"\n  {C.YEL}{t('no_drives')}{C.R}")
            return
        for i, d in enumerate(results, 1):
            print_drive(d, i, len(results))
        if commands:
            print_smartctl_commands(results)

    if args.watch:
        try:
            while True:
                if not args.json:
                    os.system("cls" if sys.platform == "win32" else "clear")
                results = once()
                render(results, commands=False)  # keep it short so it fits the screen
                if not args.json:
                    print(f"\n{C.DIM}  {t('refresh', n=args.watch)}{C.R}")
                time.sleep(max(3, args.watch))
        except KeyboardInterrupt:
            print(f"\n{t('stopped')}")
            return 0

    results = once()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        render(results)
        if results:
            print()
    emit(buf.getvalue())
    if not results:
        return 11
    return exit_code_for(results) if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
