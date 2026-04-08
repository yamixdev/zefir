import aiohttp

from bot.config import config

WEATHER_CONDITIONS = {
    "Thunderstorm": "⛈️ Гроза",
    "Drizzle": "🌦️ Морось",
    "Rain": "🌧️ Дождь",
    "Snow": "❄️ Снег",
    "Mist": "🌫️ Туман",
    "Haze": "🌫️ Дымка",
    "Fog": "🌫️ Туман",
    "Clear": "☀️ Ясно",
    "Clouds": "☁️ Облачно",
}

WIND_DIR = {
    (0, 22.5): "С", (22.5, 67.5): "СВ", (67.5, 112.5): "В",
    (112.5, 157.5): "ЮВ", (157.5, 202.5): "Ю", (202.5, 247.5): "ЮЗ",
    (247.5, 292.5): "З", (292.5, 337.5): "СЗ", (337.5, 360): "С",
}


def _wind_direction(deg: float) -> str:
    for (lo, hi), name in WIND_DIR.items():
        if lo <= deg < hi:
            return name
    return ""


async def get_weather(city: str = "Москва") -> str:
    if not config.openweathermap_api_key:
        return "❌ API ключ OpenWeatherMap не настроен."

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": config.openweathermap_api_key,
        "units": "metric",
        "lang": "ru",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 404:
                return f"❌ Город <b>{city}</b> не найден."
            if resp.status != 200:
                return "❌ Не удалось получить погоду. Попробуй позже."
            data = await resp.json()

    main_weather = data["weather"][0]["main"]
    condition = WEATHER_CONDITIONS.get(main_weather, data["weather"][0]["description"])
    temp = data["main"]["temp"]
    feels = data["main"]["feels_like"]
    humidity = data["main"]["humidity"]
    wind = data["wind"]["speed"]
    wind_deg = data["wind"].get("deg", 0)
    pressure = round(data["main"]["pressure"] * 0.750062, 1)  # hPa → mmHg

    return (
        f"🌤️ <b>Погода в {city}:</b>\n\n"
        f"{condition}\n"
        f"🌡️ Температура: {temp:.0f}°C (ощущается {feels:.0f}°C)\n"
        f"💨 Ветер: {wind} м/с, {_wind_direction(wind_deg)}\n"
        f"💧 Влажность: {humidity}%\n"
        f"📊 Давление: {pressure} мм рт. ст."
    )
