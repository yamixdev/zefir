"""Погода: OpenWeatherMap (сейчас + 5 дней) + Open-Meteo (7 дней).

OWM /geo/1.0/direct даёт до 5 кандидатов на один запрос города — решает
известную боль, когда «Москва» находится в нескольких штатах США. Храним
lat/lon, все последующие запросы идут по координатам.

5-дневный прогноз агрегируется из 3-часовых точек: группируем по
локальной дате города (используя city.timezone offset), берём min/max
температуру и состояние из точки ~12:00 локально.

7-дневный — Open-Meteo без API-ключа, WMO weather codes маппим на свои
эмодзи.
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from bot.config import config

logger = logging.getLogger("зефирка.погода")

OWM_BASE = "https://api.openweathermap.org"
OM_URL = "https://api.open-meteo.com/v1/forecast"


# ── OWM condition (main) → emoji + подпись ───────────────────────
_OWM_CONDITIONS = {
    "Thunderstorm": ("⛈", "Гроза"),
    "Drizzle":      ("🌦", "Морось"),
    "Rain":         ("🌧", "Дождь"),
    "Snow":         ("❄️", "Снег"),
    "Mist":         ("🌫", "Туман"),
    "Haze":         ("🌫", "Дымка"),
    "Fog":          ("🌫", "Туман"),
    "Smoke":        ("🌫", "Дым"),
    "Dust":         ("🌫", "Пыль"),
    "Sand":         ("🌫", "Песок"),
    "Ash":          ("🌫", "Пепел"),
    "Squall":       ("💨", "Шквал"),
    "Tornado":      ("🌪", "Торнадо"),
    "Clear":        ("☀️", "Ясно"),
    "Clouds":       ("☁️", "Облачно"),
}

# WMO weather codes → emoji + подпись (Open-Meteo)
_WMO = {
    0:  ("☀️", "Ясно"),
    1:  ("🌤", "Малооблачно"),
    2:  ("⛅", "Переменная облачность"),
    3:  ("☁️", "Пасмурно"),
    45: ("🌫", "Туман"),
    48: ("🌫", "Изморозь"),
    51: ("🌦", "Морось"),
    53: ("🌦", "Морось"),
    55: ("🌦", "Сильная морось"),
    56: ("🌧", "Ледяная морось"),
    57: ("🌧", "Ледяная морось"),
    61: ("🌧", "Дождь"),
    63: ("🌧", "Дождь"),
    65: ("🌧", "Сильный дождь"),
    66: ("🌧", "Ледяной дождь"),
    67: ("🌧", "Ледяной дождь"),
    71: ("❄️", "Снег"),
    73: ("❄️", "Снег"),
    75: ("❄️", "Сильный снег"),
    77: ("❄️", "Снежная крупа"),
    80: ("🌦", "Ливень"),
    81: ("🌧", "Сильный ливень"),
    82: ("⛈", "Проливной дождь"),
    85: ("🌨", "Снегопад"),
    86: ("🌨", "Сильный снегопад"),
    95: ("⛈", "Гроза"),
    96: ("⛈", "Гроза с градом"),
    99: ("⛈", "Сильная гроза"),
}

_WIND_DIR = [
    (0, 22.5, "С"), (22.5, 67.5, "СВ"), (67.5, 112.5, "В"),
    (112.5, 157.5, "ЮВ"), (157.5, 202.5, "Ю"), (202.5, 247.5, "ЮЗ"),
    (247.5, 292.5, "З"), (292.5, 337.5, "СЗ"), (337.5, 360.1, "С"),
]


def _wind_dir(deg: float) -> str:
    for lo, hi, name in _WIND_DIR:
        if lo <= deg < hi:
            return name
    return ""


def _hpa_to_mmhg(hpa: float) -> float:
    return hpa * 0.750062


def _weekday_ru(dt: datetime) -> str:
    return ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][dt.weekday()]


async def _get_json(url: str, params: dict) -> Any:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.warning("🌤 %s вернул %s: %s", url, resp.status, data)
                return None
            return data


# ── Geocoding ──────────────────────────────────────────────────

async def geocode(query: str, limit: int = 5) -> list[dict]:
    """Возвращает кандидатов: [{name, country, state, lat, lon, label}]."""
    if not config.openweathermap_api_key or not query:
        return []
    data = await _get_json(f"{OWM_BASE}/geo/1.0/direct", {
        "q": query,
        "limit": limit,
        "appid": config.openweathermap_api_key,
    })
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        name = (item.get("local_names") or {}).get("ru") or item.get("name") or ""
        country = item.get("country") or ""
        state = item.get("state") or ""
        label = name
        extras = ", ".join(x for x in (state, country) if x)
        if extras:
            label = f"{name} ({extras})"
        out.append({
            "name": name,
            "country": country,
            "state": state,
            "lat": item["lat"],
            "lon": item["lon"],
            "label": label,
        })
    return out


# ── Now (OWM current) ───────────────────────────────────────────

async def format_current(lat: float, lon: float, city_label: str) -> str:
    data = await _get_json(f"{OWM_BASE}/data/2.5/weather", {
        "lat": lat, "lon": lon,
        "units": "metric", "lang": "ru",
        "appid": config.openweathermap_api_key,
    })
    if not data:
        return "❌ Не удалось получить погоду. Попробуй позже."

    main = data["weather"][0]["main"]
    icon, desc = _OWM_CONDITIONS.get(main, ("🌤", data["weather"][0]["description"].capitalize()))
    temp = data["main"]["temp"]
    feels = data["main"]["feels_like"]
    humidity = data["main"]["humidity"]
    wind = data["wind"]["speed"]
    wind_deg = data["wind"].get("deg", 0)
    pressure = round(_hpa_to_mmhg(data["main"]["pressure"]), 1)

    return (
        f"🌤 <b>Сейчас в {city_label}</b>\n\n"
        f"{icon} <b>{desc}</b>\n"
        f"🌡 Температура: <b>{temp:+.0f}°C</b> (ощущается {feels:+.0f}°C)\n"
        f"💨 Ветер: {wind:.0f} м/с, {_wind_dir(wind_deg)}\n"
        f"💧 Влажность: {humidity}%\n"
        f"📊 Давление: {pressure:.0f} мм рт. ст."
    )


# ── 5 days (OWM forecast, 3h granularity) ──────────────────────

async def format_5day(lat: float, lon: float, city_label: str) -> str:
    data = await _get_json(f"{OWM_BASE}/data/2.5/forecast", {
        "lat": lat, "lon": lon,
        "units": "metric", "lang": "ru",
        "appid": config.openweathermap_api_key,
    })
    if not data:
        return "❌ Не удалось получить прогноз. Попробуй позже."

    tz_offset_sec = data.get("city", {}).get("timezone", 0)
    tz = timezone(timedelta(seconds=tz_offset_sec))

    # Группируем 3-часовые точки по локальной дате
    by_date: dict[str, list[dict]] = {}
    for item in data["list"]:
        local = datetime.fromtimestamp(item["dt"], tz=tz)
        key = local.strftime("%Y-%m-%d")
        by_date.setdefault(key, []).append({"local": local, "item": item})

    lines = [f"📅 <b>Прогноз на 5 дней — {city_label}</b>\n"]
    today = datetime.now(tz).strftime("%Y-%m-%d")
    for date_key in sorted(by_date.keys())[:5]:
        points = by_date[date_key]
        temps = [p["item"]["main"]["temp"] for p in points]
        tmin = min(temps)
        tmax = max(temps)

        # Выбираем точку ближе к 12:00 локально для состояния
        noon = min(points, key=lambda p: abs(p["local"].hour - 12))
        main_cond = noon["item"]["weather"][0]["main"]
        icon, desc = _OWM_CONDITIONS.get(main_cond, ("🌤", ""))
        # Если в течение дня был дождь/гроза — вешаем его значок, а не ясный полдень
        conds = Counter(p["item"]["weather"][0]["main"] for p in points)
        for priority in ("Thunderstorm", "Snow", "Rain", "Drizzle"):
            if priority in conds and priority != main_cond:
                icon, desc = _OWM_CONDITIONS[priority]
                break

        local_date = datetime.strptime(date_key, "%Y-%m-%d").replace(tzinfo=tz)
        day_label = _weekday_ru(local_date) + " " + local_date.strftime("%d.%m")
        if date_key == today:
            day_label = "Сегодня " + local_date.strftime("%d.%m")

        lines.append(
            f"{icon} <b>{day_label}</b> — {tmin:+.0f}°…{tmax:+.0f}° · {desc}"
        )
    return "\n".join(lines)


# ── 7 days (Open-Meteo, no key) ────────────────────────────────

async def format_7day(lat: float, lon: float, city_label: str) -> str:
    data = await _get_json(OM_URL, {
        "latitude": lat,
        "longitude": lon,
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "auto",
        "forecast_days": 7,
    })
    if not data or "daily" not in data:
        return "❌ Не удалось получить прогноз на неделю. Попробуй позже."

    daily = data["daily"]
    dates = daily["time"]
    tmax = daily["temperature_2m_max"]
    tmin = daily["temperature_2m_min"]
    codes = daily["weathercode"]
    precip = daily.get("precipitation_sum") or [0] * len(dates)

    today_str = datetime.now().strftime("%Y-%m-%d")
    lines = [f"📆 <b>Прогноз на 7 дней — {city_label}</b>\n<i>Open-Meteo</i>\n"]
    for i, d in enumerate(dates):
        icon, desc = _WMO.get(codes[i], ("🌤", ""))
        dt = datetime.strptime(d, "%Y-%m-%d")
        day_label = _weekday_ru(dt) + " " + dt.strftime("%d.%m")
        if d == today_str:
            day_label = "Сегодня " + dt.strftime("%d.%m")
        rain = f" · 💧 {precip[i]:.1f} мм" if precip[i] and precip[i] > 0.1 else ""
        lines.append(
            f"{icon} <b>{day_label}</b> — {tmin[i]:+.0f}°…{tmax[i]:+.0f}° · {desc}{rain}"
        )
    return "\n".join(lines)
