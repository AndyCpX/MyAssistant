"""Skill meteo: geocoding + previsione con Open-Meteo (gratuito, senza chiave)."""
import httpx

_CODICI = {0: "sereno", 1: "prevalentemente sereno", 2: "parzialmente nuvoloso", 3: "coperto", 45: "nebbia", 48: "nebbia",
           51: "pioggerella", 53: "pioggerella", 55: "pioggerella", 61: "pioggia debole", 63: "pioggia", 65: "pioggia forte",
           71: "neve debole", 73: "neve", 75: "neve forte", 80: "rovesci", 81: "rovesci", 82: "rovesci forti",
           95: "temporale", 96: "temporale con grandine", 99: "temporale con grandine"}


async def meteo(citta: str, giorni: int = 1) -> dict:
    """Tempo attuale e previsione per una città.

    Args:
        citta: nome della città, ad esempio "Milano".
        giorni: quanti giorni di previsione (1 = oggi, massimo 3).
    """
    giorni = max(1, min(int(giorni), 3))
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            g = (await c.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": citta, "count": 1, "language": "it"})).json()
            if not g.get("results"):
                return {"error": f"città non trovata: {citta}"}
            p = g["results"][0]
            f = (await c.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": p["latitude"], "longitude": p["longitude"], "timezone": "auto", "forecast_days": giorni,
                "current": "temperature_2m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})).json()
    except (httpx.HTTPError, ValueError):
        return {"error": "servizio meteo non raggiungibile"}
    d = f["daily"]
    giorni_out = [{"data": d["time"][i], "cielo": _CODICI.get(d["weather_code"][i], "variabile"),
                   "min": round(d["temperature_2m_min"][i]), "max": round(d["temperature_2m_max"][i]),
                   "prob_pioggia_pct": d["precipitation_probability_max"][i]} for i in range(len(d["time"]))]
    return {"citta": p["name"], "ora": {"temp": round(f["current"]["temperature_2m"]),
                                         "cielo": _CODICI.get(f["current"]["weather_code"], "variabile")},
            "previsione": giorni_out}
