"""
recipe_parser.py - Powered by Google Gemini 2.5 Flash (Async Version)
"""

import json
import os
from google import genai
from google.genai import types

_client: genai.Client | None = None

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()
    return _client

KNOWN_CATEGORIES = [
    "Dairy", "Vegetables", "Fruits", "Meat & Poultry", "Fish & Seafood",
    "Bakery", "Grains & Pasta", "Canned & Jarred", "Spices & Condiments",
    "Frozen", "Beverages", "Household", "Other",
]

SYSTEM_PROMPT = f"""You are a grocery-list assistant. Your job is to convert recipe content 
(which could be text, text scraped from a website, or an image of a recipe) into a clean, structured shopping list.

Rules:
1. Extract only actual purchasable grocery ingredients. Skip water, ice, "to taste" fillers, and kitchen tools.
2. Translate ingredient names to Hebrew (עברית) so they match the family grocery store items.
3. Merge duplicate ingredients into a single line with a combined quantity.
4. Normalize quantities into short shopping-friendly units (e.g., "2", "500 גרם", "1 חבילה").
5. Assign each ingredient the closest category from this fixed English list: {", ".join(KNOWN_CATEGORIES)}.
"""

async def parse_recipe_text(raw_text: str) -> list[dict]:
    return await _call_gemini_async(contents=raw_text)

async def parse_recipe_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> list[dict]:
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    return await _call_gemini_async(contents=image_part)

async def _call_gemini_async(contents) -> list[dict]:
    client = _get_client()
    try:
        # שימוש ב-client.aio.models עבור קריאה אסינכרונית שלא תוקעת את השרת
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "name": types.Schema(type=types.Type.STRING),
                            "quantity": types.Schema(type=types.Type.STRING),
                            "category": types.Schema(type=types.Type.STRING),
                        },
                        required=["name", "quantity", "category"],
                    ),
                ),
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Gemini Async Error: {e}")
        return []