"""Reads nutrition labels and estimates meals from photos using Claude."""
import base64
import json

import anthropic

from . import config

_NUM = {"type": "number"}
_NULL_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}

LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "is_label": {"type": "boolean"},
        "name": {"type": "string"},
        "serving_desc": {"type": "string"},
        "serving_g": _NULL_NUM,
        "servings_per_container": _NULL_NUM,
        "carbs_g": _NUM,
        "fat_g": _NUM,
        "notes": {"type": "string"},
    },
    "required": ["is_label", "name", "serving_desc", "serving_g", "servings_per_container",
                 "carbs_g", "fat_g", "notes"],
    "additionalProperties": False,
}

MEAL_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "portion_desc": {"type": "string"},
                    "grams": _NUM,
                    "carbs_g": _NUM,
                    "fat_g": _NUM,
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["name", "portion_desc", "grams", "carbs_g", "fat_g", "confidence"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["items", "notes"],
    "additionalProperties": False,
}

LABEL_PROMPT = (
    "This is a photo of a packaged food's nutrition facts label. Read it exactly. "
    "Report values PER SERVING as printed: carbs_g is Total Carbohydrate, fat_g is Total Fat. "
    "serving_desc is the printed serving size (e.g. '2/3 cup (55g)'); serving_g is the gram weight if printed, else null. "
    "Use the product name if visible, otherwise a short description. "
    "If the photo is not a nutrition label, set is_label false and zeros. Mention any legibility problems in notes."
)

MEAL_PROMPT = (
    "This is a photo of a meal or food. Identify each distinct food item and estimate its portion size in grams "
    "using visible cues (plate, utensils, packaging), then estimate total carbohydrate and total fat for that portion "
    "using standard nutrition data. Be realistic rather than conservative. Use confidence 'low' when the portion or "
    "preparation (oil, sauces, breading) is hard to judge. Put hidden-ingredient caveats in notes."
)


class VisionError(Exception):
    pass


def _client() -> anthropic.Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise VisionError("ANTHROPIC_API_KEY is not set on the server")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def sniff_media_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    raise VisionError("Unsupported image type; use JPEG, PNG, WebP or GIF")


def _analyze(image: bytes, prompt: str, schema: dict, hint: str = "") -> dict:
    media_type = sniff_media_type(image)
    text = prompt + (f"\n\nThe user adds: {hint}" if hint.strip() else "")
    try:
        response = _client().messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                             "data": base64.standard_b64encode(image).decode()}},
                {"type": "text", "text": text},
            ]}],
        )
    except anthropic.APIError as e:
        raise VisionError(f"Claude API error: {getattr(e, 'message', e)}") from e
    if response.stop_reason == "refusal":
        raise VisionError("Claude declined to analyse this image")
    if response.stop_reason == "max_tokens":
        raise VisionError("Response was cut off; try a clearer or simpler photo")
    body = next((b.text for b in response.content if b.type == "text"), None)
    if not body:
        raise VisionError("Claude returned no result")
    return json.loads(body)


def read_label(image: bytes, hint: str = "") -> dict:
    return _analyze(image, LABEL_PROMPT, LABEL_SCHEMA, hint)


def estimate_meal(image: bytes, hint: str = "") -> dict:
    return _analyze(image, MEAL_PROMPT, MEAL_SCHEMA, hint)
