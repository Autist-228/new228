CITIES = {
    "nyc": {
        "name": "New York City",
        "slug_name": "nyc",
        "lat": 40.7772,
        "lon": -73.8726,
        "unit": "fahrenheit",
        "timezone": "America/New_York",
    },
    "london": {
        "name": "London",
        "slug_name": "london",
        "lat": 51.5053,
        "lon": 0.0553,
        "unit": "celsius",
        "timezone": "Europe/London",
    },
    "miami": {
        "name": "Miami",
        "slug_name": "miami",
        "lat": 25.7959,
        "lon": -80.2870,
        "unit": "fahrenheit",
        "timezone": "America/New_York",
    },
    "dallas": {
        "name": "Dallas",
        "slug_name": "dallas",
        "lat": 32.8471,
        "lon": -96.8518,
        "unit": "fahrenheit",
        "timezone": "America/Chicago",
    },
    "seoul": {
        "name": "Seoul",
        "slug_name": "seoul",
        "lat": 37.4691,
        "lon": 126.4505,
        "unit": "celsius",
        "timezone": "Asia/Seoul",
    },
    "buenos_aires": {
        "name": "Buenos Aires",
        "slug_name": "buenos-aires",
        "lat": -34.8222,
        "lon": -58.5358,
        "unit": "celsius",
        "timezone": "America/Argentina/Buenos_Aires",
    },
    "toronto": {
        "name": "Toronto",
        "slug_name": "toronto",
        "lat": 43.6777,
        "lon": -79.6248,
        "unit": "celsius",
        "timezone": "America/Toronto",
    },
    "seattle": {
        "name": "Seattle",
        "slug_name": "seattle",
        "lat": 47.4502,
        "lon": -122.3088,
        "unit": "fahrenheit",
        "timezone": "America/Los_Angeles",
    },
    "chicago": {
        "name": "Chicago",
        "slug_name": "chicago",
        "lat": 41.9742,
        "lon": -87.9073,
        "unit": "fahrenheit",
        "timezone": "America/Chicago",
    },
    "atlanta": {
        "name": "Atlanta",
        "slug_name": "atlanta",
        "lat": 33.6407,
        "lon": -84.4277,
        "unit": "fahrenheit",
        "timezone": "America/New_York",
    },
    "ankara": {
        "name": "Ankara",
        "slug_name": "ankara",
        "lat": 40.1281,
        "lon": 32.9950,
        "unit": "celsius",
        "timezone": "Europe/Istanbul",
    },
    "paris": {
        "name": "Paris",
        "slug_name": "paris",
        "lat": 49.0097,
        "lon": 2.5478,
        "unit": "celsius",
        "timezone": "Europe/Paris",
    },
    "wellington": {
        "name": "Wellington",
        "slug_name": "wellington",
        "lat": -41.3272,
        "lon": 174.8053,
        "unit": "celsius",
        "timezone": "Pacific/Auckland",
    },
    "sao_paulo": {
        "name": "Sao Paulo",
        "slug_name": "sao-paulo",
        "lat": -23.4356,
        "lon": -46.4731,
        "unit": "celsius",
        "timezone": "America/Sao_Paulo",
    },
}

PRECIPITATION_CITIES = {
    "nyc": {
        "slug_pattern": "precipitation-in-nyc-in-{month_lower}",
        "lat": 40.7772,
        "lon": -73.8726,
        "unit": "inch",
        "timezone": "America/New_York",
    },
    "seattle": {
        "slug_pattern": "precipitation-in-seattle-in-{month_lower}",
        "lat": 47.4502,
        "lon": -122.3088,
        "unit": "inch",
        "timezone": "America/Los_Angeles",
    },
}

CLIMATE_EVENT_SLUGS = [
    "february-2026-temperature-increase-c",
    "will-a-hurricane-form-by-may-31",
    "where-will-2026-rank-among-the-hottest-years-on-record",
    "how-many-7-0-or-above-earthquakes-by-june-30",
    "how-many-6-5-or-above-earthquakes-february-16-february-22",
    "2026-february-1st-2nd-3rd-hottest-on-record",
    "10-0-or-above-earthquake-before-2027",
]

GAMMA_API_URL = "https://gamma-api.polymarket.com"

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

EDGE_THRESHOLD = 0.30

LOTTERY_MIN_PRICE = 0.01
LOTTERY_MAX_PRICE = 0.20

SPREAD_BET_AMOUNT = 1.0
SPREAD_MAX_PRICE = 0.20

FORECAST_DAYS = 3

MIN_LIQUIDITY = 100

SCAN_INTERVAL_SECONDS = 300
