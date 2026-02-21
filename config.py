CITIES = {
    "nyc": {
        "name": "New York City",
        "slug_name": "nyc",
        "lat": 40.7128,
        "lon": -74.0060,
        "unit": "fahrenheit",
        "timezone": "America/New_York",
    },
    "london": {
        "name": "London",
        "slug_name": "london",
        "lat": 51.5074,
        "lon": -0.1278,
        "unit": "celsius",
        "timezone": "Europe/London",
    },
    "miami": {
        "name": "Miami",
        "slug_name": "miami",
        "lat": 25.7617,
        "lon": -80.1918,
        "unit": "fahrenheit",
        "timezone": "America/New_York",
    },
    "dallas": {
        "name": "Dallas",
        "slug_name": "dallas",
        "lat": 32.7767,
        "lon": -96.7970,
        "unit": "fahrenheit",
        "timezone": "America/Chicago",
    },
    "seoul": {
        "name": "Seoul",
        "slug_name": "seoul",
        "lat": 37.5665,
        "lon": 126.9780,
        "unit": "celsius",
        "timezone": "Asia/Seoul",
    },
    "buenos_aires": {
        "name": "Buenos Aires",
        "slug_name": "buenos-aires",
        "lat": -34.6037,
        "lon": -58.3816,
        "unit": "celsius",
        "timezone": "America/Argentina/Buenos_Aires",
    },
    "toronto": {
        "name": "Toronto",
        "slug_name": "toronto",
        "lat": 43.6532,
        "lon": -79.3832,
        "unit": "celsius",
        "timezone": "America/Toronto",
    },
    "seattle": {
        "name": "Seattle",
        "slug_name": "seattle",
        "lat": 47.6062,
        "lon": -122.3321,
        "unit": "fahrenheit",
        "timezone": "America/Los_Angeles",
    },
    "chicago": {
        "name": "Chicago",
        "slug_name": "chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "unit": "fahrenheit",
        "timezone": "America/Chicago",
    },
    "atlanta": {
        "name": "Atlanta",
        "slug_name": "atlanta",
        "lat": 33.7490,
        "lon": -84.3880,
        "unit": "fahrenheit",
        "timezone": "America/New_York",
    },
    "ankara": {
        "name": "Ankara",
        "slug_name": "ankara",
        "lat": 39.9334,
        "lon": 32.8597,
        "unit": "celsius",
        "timezone": "Europe/Istanbul",
    },
    "paris": {
        "name": "Paris",
        "slug_name": "paris",
        "lat": 48.8566,
        "lon": 2.3522,
        "unit": "celsius",
        "timezone": "Europe/Paris",
    },
    "wellington": {
        "name": "Wellington",
        "slug_name": "wellington",
        "lat": -41.2865,
        "lon": 174.7762,
        "unit": "celsius",
        "timezone": "Pacific/Auckland",
    },
    "sao_paulo": {
        "name": "Sao Paulo",
        "slug_name": "sao-paulo",
        "lat": -23.5505,
        "lon": -46.6333,
        "unit": "celsius",
        "timezone": "America/Sao_Paulo",
    },
}

PRECIPITATION_CITIES = {
    "nyc": {
        "slug_pattern": "precipitation-in-nyc-in-{month_lower}",
        "lat": 40.7128,
        "lon": -74.0060,
        "unit": "inch",
        "timezone": "America/New_York",
    },
    "seattle": {
        "slug_pattern": "precipitation-in-seattle-in-{month_lower}",
        "lat": 47.6062,
        "lon": -122.3321,
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

EDGE_THRESHOLD = 0.15

FORECAST_DAYS = 3

MIN_LIQUIDITY = 100

SCAN_INTERVAL_SECONDS = 60
