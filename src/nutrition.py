import json
from datetime import date, datetime
from typing import Any

import google.generativeai as genai
from pydantic import BaseModel, Field

MEAL_LOG_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_food_log": {"type": "boolean"},
        "consumed_at": {"type": "string"},
        "calories": {"type": "integer"},
        "protein_g": {"type": "integer"},
        "carbs_g": {"type": "integer"},
        "fats_g": {"type": "integer"},
        "product_name": {"type": "string"},
        "source_type": {"type": "string"},
    },
    "required": ["is_food_log", "consumed_at", "calories", "protein_g", "carbs_g", "fats_g"],
}

# Define the exact contract your database requires
class MealLog(BaseModel):
    is_food_log: bool = Field(
        description=(
            "True only if the user is reporting specific food or drinks they ate or drank "
            "in this message. False for questions, summaries, goal-setting, targets, "
            "or general conversation about nutrition."
        )
    )
    consumed_at: str = Field(
        description=(
            "Best estimate of when the food was consumed, as ISO 8601 datetime "
            "(e.g. 2026-07-03T08:00:00). Infer from timing phrases in the user's message "
            "such as 'this morning', 'for breakfast', 'last night for dinner', or "
            "'yesterday at lunch', relative to reference_time. If no timing is mentioned, "
            "use reference_time."
        )
    )
    calories: int = Field(description="Total calculated calories for the logged items.")
    protein_g: int = Field(description="Grams of protein.")
    carbs_g: int = Field(description="Grams of carbohydrates.")
    fats_g: int = Field(description="Grams of dietary fats.")
    product_name: str | None = Field(default=None)
    source_type: str | None = Field(default=None)  # e.g. "commercial_product"


def _resolve_meal_timestamp(inferred: str, reference_time: datetime) -> str:
    """Use model-inferred consumed_at when valid; otherwise fall back to reference_time."""
    try:
        return datetime.fromisoformat(inferred).isoformat()
    except (TypeError, ValueError):
        return reference_time.isoformat()


def should_save_nutrition_log(nutrition: dict[str, Any]) -> bool:
    """Return True when the exchange represents a concrete food entry or a pending food mention."""
    if nutrition.get("is_food_log") is not True:
        return False

    has_explicit_food_reference = bool(
        nutrition.get("product_name") or nutrition.get("raw_food_input")
    )
    has_calories = nutrition.get("calories", 0) > 0
    return has_explicit_food_reference or has_calories


def _filter_logs_for_range(
    nutrition_logs: list[dict[str, Any]], start_date: date, end_date: date
) -> list[dict[str, Any]]:
    filtered = []
    for log in nutrition_logs:
        timestamp = log.get("timestamp")
        if not timestamp:
            continue
        try:
            entry_date = datetime.fromisoformat(timestamp).date()
        except ValueError:
            continue
        if entry_date < start_date:
            continue
        if entry_date > end_date:
            break
        filtered.append(log)
    return filtered


def _format_period_label(start_date: date, end_date: date) -> str:
    today = date.today()
    if start_date == end_date:
        if start_date == today:
            return "today"
        return start_date.isoformat()
    return f"{start_date.isoformat()} to {end_date.isoformat()}"


def _format_header_label(start_date: date, end_date: date) -> str:
    today = date.today()
    if start_date == end_date == today:
        return "TODAY'S LOG PARAMETERS"
    if start_date == end_date:
        return f"{start_date.isoformat()} LOG PARAMETERS"
    return f"{start_date.isoformat()} to {end_date.isoformat()} LOG PARAMETERS"


def _calculate_totals_for_range(
    nutrition_logs: list[dict[str, Any]],
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    range_logs = _filter_logs_for_range(nutrition_logs, start_date, end_date)
    return {
        "calories": sum(log.get("calories", 0) for log in range_logs),
        "protein_g": sum(log.get("protein_g", 0) for log in range_logs),
        "carbs_g": sum(log.get("carbs_g", 0) for log in range_logs),
        "fats_g": sum(log.get("fats_g", 0) for log in range_logs),
    }


def build_daily_summary_header(
    user_profile: dict[str, Any],
    nutrition_logs: list[dict[str, Any]],
    start_date: date | None = None,
    end_date: date | None = None,
) -> str:
    target_start = start_date or date.today()
    target_end = end_date or target_start
    if target_start > target_end:
        target_start, target_end = target_end, target_start

    totals = _calculate_totals_for_range(nutrition_logs, target_start, target_end)
    calorie_target = user_profile.get("tdee_target")
    protein_target = user_profile.get("protein_target_g")
    carb_target = user_profile.get("net_carb_target_g")
    fat_target = user_profile.get("fat_target_g")

    target_parts = []
    if calorie_target is not None:
        target_parts.append(f"Target: {calorie_target} kcal")
    if protein_target is not None:
        target_parts.append(f"Target: {protein_target} g")
    if carb_target is not None:
        target_parts.append(f"Target: {carb_target} g")
    if fat_target is not None:
        target_parts.append(f"Target: {fat_target} g")

    summary = [
        "Current Daily Stats:",
        f"Calories: {totals['calories']} kcal",
        f"Protein: {totals['protein_g']} g",
        f"Carbs: {totals['carbs_g']} g",
        f"Fat: {totals['fats_g']} g",
    ]
    if target_parts:
        summary.append("")
        summary.extend(target_parts)
    return "\n".join(summary)


def build_daily_log_notification(
    user_profile: dict[str, Any],
    nutrition_logs: list[dict[str, Any]],
    start_date: date | None = None,
    end_date: date | None = None,
) -> str:
    """
    Summarize tracked nutrition for a calendar date range as a system notification string.
    nutrition_logs are assumed to be sorted earliest to latest.
    user_profile is accepted for future target-aware messaging.
    """
    target_start = start_date or date.today()
    target_end = end_date or target_start
    if target_start > target_end:
        target_start, target_end = target_end, target_start

    totals = _calculate_totals_for_range(nutrition_logs, target_start, target_end)

    header = _format_header_label(target_start, target_end)
    period_label = _format_period_label(target_start, target_end)

    return f"""[SYSTEM NOTIFICATION - {header}]
    The user's tracked consumption for {period_label} stands at:
    - Calories consumed: {totals["calories"]} kcal
    - Protein: {totals["protein_g"]} g
    - Carbs: {totals["carbs_g"]} g
    - Fat: {totals["fats_g"]} g
    [END SYSTEM NOTIFICATION]"""

def extract_structured_nutrition(
    user_text: str,
    ai_response: str,
    reference_time: datetime | None = None,
) -> dict:
    """
    Asynchronous extraction worker that listens to the exchange,
    isolates the metrics, and formats them into clean data points.
    """
    logged_at = reference_time or datetime.now()
    extractor_model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite", # Lite is perfect for fast schema formatting
        system_instruction=f"""
        You are a backend database extraction parser. Analyze the conversation exchange.
        reference_time is when the user sent this message: {logged_at.isoformat()}

        Set is_food_log to true when the user is reporting specific food or drinks
        they actually consumed, including restaurant items, packaged foods, or commercial products.

        Treat the message as a food log when the user mentions:
        - a specific dish, ingredient, meal, snack, or beverage
        - a restaurant item or commercial product name
        - and either provides explicit calories/macros or clearly describes a food item they ate

        Set is_food_log to false for:
        - Questions or requests (e.g. "summarize my calories", "what did I eat?", "How many calories does an apple have?")
        - Goal or target setting (e.g. "let's go with 3000 calories", "200g protein minimum")
        - BMR/TDEE discussions, profile updates, or general coaching chat
        - Messages with no concrete foods or drinks consumed

        When is_food_log is false, return 0 for all macro fields and set consumed_at to reference_time.
        When is_food_log is true, extract or estimate nutrition for the consumed items only.
        If the user provides calories but not macros, estimate plausible protein, carbs, and fats based on the food type.
        If no calorie or macro values are provided, return 0 for those fields and preserve the product_name or food description.

        For consumed_at, infer when the food was eaten relative to reference_time:
        - "this morning" / "for breakfast" -> same calendar day, ~08:00
        - "for lunch" -> same calendar day, ~12:00
        - "this afternoon" / "for a snack" -> same calendar day, ~15:00
        - "for dinner" / "this evening" -> same calendar day, ~18:00
        - "last night" -> previous calendar day, ~20:00
        - "yesterday" + meal -> previous calendar day at that meal's typical hour
        If no timing is mentioned, use reference_time.
        """
    )
    
    analysis_payload = (
        f"reference_time: {logged_at.isoformat()}\n"
        f"User said: {user_text}\n"
        f"Coach responded: {ai_response}"
    )
    
    # Force Gemini to strictly conform to our Pydantic class structure
    response = extractor_model.generate_content(
        analysis_payload,
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": MEAL_LOG_RESPONSE_SCHEMA,
        },
    )
    
    # Parse the guaranteed JSON string back into a clean dictionary
    data_dict = json.loads(response.text)
    data_dict["timestamp"] = _resolve_meal_timestamp(
        data_dict.pop("consumed_at", ""), logged_at
    )
    data_dict["raw_food_input"] = user_text
    return data_dict