"""Online nutrition lookups: Open Food Facts (packaged/barcodes) and USDA FoodData Central (generic)."""
import httpx

from . import config

OFF = "https://world.openfoodfacts.org"
USDA = "https://api.nal.usda.gov/fdc/v1"
HEADERS = {"User-Agent": config.USER_AGENT}
TIMEOUT = 10.0


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _food(name, brand, source, carbs_100g, fat_100g, serving_g=None, serving_desc="", barcode=None):
    """Normalised result. Per-serving values are derived from per-100g when the serving weight is known."""
    if carbs_100g is None or fat_100g is None:
        return None
    food = {
        "name": name,
        "brand": brand or "",
        "source": source,
        "barcode": barcode,
        "carbs_100g": carbs_100g,
        "fat_100g": fat_100g,
        "serving_g": serving_g,
        "serving_desc": serving_desc,
    }
    if serving_g:
        food["carbs_serving"] = round(carbs_100g * serving_g / 100, 2)
        food["fat_serving"] = round(fat_100g * serving_g / 100, 2)
    return food


def parse_off_product(p: dict):
    n = p.get("nutriments") or {}
    name = p.get("product_name") or p.get("generic_name")
    if not name:
        return None
    return _food(
        name,
        (p.get("brands") or "").split(",")[0].strip(),
        "openfoodfacts",
        _num(n.get("carbohydrates_100g")),
        _num(n.get("fat_100g")),
        _num(p.get("serving_quantity")),
        p.get("serving_size") or "",
        p.get("code"),
    )


def parse_usda_food(f: dict):
    values = {}
    for nutrient in f.get("foodNutrients", []):
        nid = nutrient.get("nutrientId") or (nutrient.get("nutrient") or {}).get("id")
        values[nid] = nutrient.get("value", nutrient.get("amount"))
    serving_g = None
    if (f.get("servingSizeUnit") or "").lower() in ("g", "grm"):
        serving_g = _num(f.get("servingSize"))
    desc = f.get("householdServingFullText") or (f"{serving_g:g} g" if serving_g else "")
    return _food(
        f.get("description", "").title(),
        f.get("brandName") or f.get("brandOwner") or "",
        "usda",
        _num(values.get(1005)),
        _num(values.get(1004)),
        serving_g,
        desc,
        f.get("gtinUpc"),
    )


def barcode(code: str):
    r = httpx.get(f"{OFF}/api/v2/product/{code}.json", headers=HEADERS, timeout=TIMEOUT,
                  params={"fields": "code,product_name,generic_name,brands,serving_size,serving_quantity,nutriments"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return parse_off_product(data["product"]) if data.get("status") == 1 else None


def _search_off(q: str):
    r = httpx.get(f"{OFF}/cgi/search.pl", headers=HEADERS, timeout=TIMEOUT, params={
        "search_terms": q, "search_simple": 1, "action": "process", "json": 1, "page_size": 10,
        "fields": "code,product_name,generic_name,brands,serving_size,serving_quantity,nutriments"})
    r.raise_for_status()
    return [parse_off_product(p) for p in r.json().get("products", [])]


def _search_usda(q: str):
    r = httpx.get(f"{USDA}/foods/search", headers=HEADERS, timeout=TIMEOUT, params={
        "query": q, "api_key": config.USDA_API_KEY, "pageSize": 10,
        "dataType": "Foundation,SR Legacy,Branded"})
    r.raise_for_status()
    return [parse_usda_food(f) for f in r.json().get("foods", [])]


def search(q: str):
    """Generic foods (USDA) first, then packaged products. One source failing doesn't fail the search."""
    results, errors = [], []
    for source, fn in (("usda", _search_usda), ("openfoodfacts", _search_off)):
        try:
            results += [f for f in fn(q) if f]
        except httpx.HTTPError as e:
            errors.append(f"{source}: {e}")
    return results, errors
