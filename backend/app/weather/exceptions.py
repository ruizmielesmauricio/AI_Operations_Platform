class WeatherProviderError(Exception):
    """Met Éireann's forecast API failed (network error, non-2xx, or a
    response that doesn't parse as the expected XML shape) — caught by
    app/application/weather_ingestion.py and app/application/
    weather_insights.py, both of which degrade quietly (skip this
    business/skip the insight) rather than let a weather-provider hiccup
    break the scheduler tick or the Findings list. No WeatherNotConfigured
    counterpart, unlike every other provider client in this codebase
    (Geoapify, Resend, R2) — Met Éireann's forecast endpoint needs no API
    key at all, confirmed live, so there's no "not configured" state to
    distinguish from a real failure.
    """
