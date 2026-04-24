"""Курсы валют от ЦБ РФ.

XML_daily.asp обновляется раз в сутки (в будни), поэтому кэшируем
на час внутри процесса. В YCF процесс живёт секунды, так что кэш
фактически помогает только внутри одной инвокации (но это не проблема —
запрос за курсами быстрый).

Отдаёт `VunitRate` (курс за 1 единицу валюты в рублях). RUB
добавляется искусственно с курсом 1.0.
"""
import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger("зефирка.валюты")

CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CACHE_TTL_SEC = 3600

# Популярные валюты для быстрых кнопок (флаг + код)
POPULAR = [
    ("🇷🇺", "RUB"),
    ("🇺🇸", "USD"),
    ("🇪🇺", "EUR"),
    ("🇨🇳", "CNY"),
    ("🇰🇿", "KZT"),
    ("🇧🇾", "BYN"),
    ("🇹🇷", "TRY"),
    ("🇬🇧", "GBP"),
    ("🇯🇵", "JPY"),
    ("🇺🇦", "UAH"),
    ("🇦🇲", "AMD"),
    ("🇦🇿", "AZN"),
]

FLAGS = dict(POPULAR) | {"GEL": "🇬🇪", "CHF": "🇨🇭", "CAD": "🇨🇦", "AUD": "🇦🇺"}


@dataclass(frozen=True)
class Currency:
    code: str       # ISO: USD
    name: str       # Доллар США
    rate_rub: float # рублей за 1 единицу


_cache: dict[str, Currency] | None = None
_cache_at: float = 0.0
_lock = asyncio.Lock()


async def _fetch_rates() -> dict[str, Currency]:
    async with aiohttp.ClientSession() as session:
        async with session.get(CBR_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            raw = await resp.read()
    text = raw.decode("windows-1251")
    root = ET.fromstring(text)

    result: dict[str, Currency] = {}
    for node in root.findall("Valute"):
        code = (node.findtext("CharCode") or "").strip()
        name = (node.findtext("Name") or "").strip()
        vunit = node.findtext("VunitRate")
        if vunit:
            rate_rub = float(vunit.replace(",", "."))
        else:
            # fallback: старый формат
            nominal = int(node.findtext("Nominal") or "1")
            value = float((node.findtext("Value") or "0").replace(",", "."))
            rate_rub = value / max(nominal, 1)
        if code:
            result[code] = Currency(code=code, name=name, rate_rub=rate_rub)
    result["RUB"] = Currency(code="RUB", name="Российский рубль", rate_rub=1.0)
    return result


async def get_rates() -> dict[str, Currency]:
    global _cache, _cache_at
    async with _lock:
        now = time.time()
        if _cache is None or now - _cache_at > CACHE_TTL_SEC:
            logger.info("💱 Обновляю курсы ЦБ РФ")
            _cache = await _fetch_rates()
            _cache_at = now
        return _cache


async def convert(amount: float, src: str, dst: str) -> float | None:
    rates = await get_rates()
    if src not in rates or dst not in rates:
        return None
    in_rub = amount * rates[src].rate_rub
    return in_rub / rates[dst].rate_rub


def flag(code: str) -> str:
    return FLAGS.get(code, "💱")
