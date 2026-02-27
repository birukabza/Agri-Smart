import httpx
import os
from dotenv import load_dotenv

load_dotenv()


async def get_isda_access_token(username: str, password: str) -> str:
    url = "https://api.isda-africa.com/login"
    headers = {
        "accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "password",
        "username": username,
        "password": password,
        "scope": "",
        "client_id": "string",
        "client_secret": "string",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=headers, data=data)
        response.raise_for_status()
        return response.json()["access_token"]


async def fetch_isda_soil_property(lat: float, lon: float, depth: str = "0-20") -> dict:
    access_token = await get_isda_access_token(
        os.getenv("ISDA_USERNAME"), os.getenv("ISDA_PASSWORD")
    )
    url = "https://api.isda-africa.com/isdasoil/v2/soilproperty"
    params = {"lat": lat, "lon": lon, "depth": depth}
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def simplify_soil_response(soil_type: dict, isda_property: dict) -> dict:
    def get_isda_value(prop_name):
        prop = isda_property.get("property", {}).get(prop_name)
        if prop and isinstance(prop, list) and prop[0].get("value"):
            return prop[0]["value"].get("value")
        return None

    def get_isda_str_value(prop_name):
        prop = isda_property.get("property", {}).get(prop_name)
        if prop and isinstance(prop, list) and prop[0].get("value"):
            return prop[0]["value"].get("value")
        return None

    texture_class = get_isda_str_value("texture_class")

    summary = {
        "soil_type": texture_class,
        "texture_class": texture_class,
        "ph": get_isda_value("ph"),
        "nitrogen_total_g_per_kg": get_isda_value("nitrogen_total"),
        "phosphorous_extractable_ppm": get_isda_value("phosphorous_extractable"),
        "potassium_extractable_ppm": get_isda_value("potassium_extractable"),
        "magnesium_extractable_ppm": get_isda_value("magnesium_extractable"),
        "calcium_extractable_ppm": get_isda_value("calcium_extractable"),
        "iron_extractable_ppm": get_isda_value("iron_extractable"),
        "zinc_extractable_ppm": get_isda_value("zinc_extractable"),
        "sulphur_extractable_ppm": get_isda_value("sulphur_extractable"),
        "carbon_total_g_per_kg": get_isda_value("carbon_total"),
        "carbon_organic_g_per_kg": get_isda_value("carbon_organic"),
        "bulk_density_g_per_cm3": get_isda_value("bulk_density"),
        "stone_content_percent": get_isda_value("stone_content"),
        "silt_content_percent": get_isda_value("silt_content"),
        "clay_content_percent": get_isda_value("clay_content"),
        "sand_content_percent": get_isda_value("sand_content"),
        "cation_exchange_capacity_cmol_per_kg": get_isda_value(
            "cation_exchange_capacity"
        ),
        "aluminium_extractable_ppm": get_isda_value("aluminium_extractable"),
    }
    return summary


async def get_soil_summary_async(
    lat: float, lon: float, depth: str = "0-20", top_k: int = 5
) -> dict:
    isda_property = await fetch_isda_soil_property(lat, lon, depth)
    return simplify_soil_response({}, isda_property)
