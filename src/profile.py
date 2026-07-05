import json
from datetime import datetime
from typing import Any

import google.generativeai as genai
from pydantic import BaseModel, Field


class WeightLogEntry(BaseModel):
    weight: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None)
    log_time: str | None = Field(default=None)


class ProfileGoal(BaseModel):
    target_weight_lb: int | None = Field(default=None, ge=1)
    target_date: str | None = Field(default=None)
    weight_log: list[WeightLogEntry] | None = Field(default=None)


class UserProfile(BaseModel):
    name: str | None = Field(default=None)
    tdee_target: int | None = Field(default=None, ge=1)
    protein_target_g: int | None = Field(default=None, ge=0)
    goal: ProfileGoal | None = Field(default=None)
    net_carb_target_g: int | None = Field(default=None, ge=0)
    fat_target_g: int | None = Field(default=None, ge=0)


def _model_dump(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)


def extract_structured_user_profile(
    user_text: str,
    ai_response: str,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """
    Parse a chat exchange and extract or update a user profile payload.
    Only fields that are explicitly present are returned.
    """
    logged_at = reference_time or datetime.now()

    extractor_model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=f"""
        You are a backend profile extraction parser.

        Analyze the chat exchange and extract any user profile information that is
        explicitly stated or clearly implied by the conversation.

        Extract these fields when present:
        - name
        - tdee_target
        - protein_target_g
        - net_carb_target_g
        - fat_target_g
        - goal.target_weight_lb
        - goal.target_date
        - goal.weight_log (an array of objects with weight, unit, and log_time)

        If a field is not present, return null for it.
        Return JSON only and preserve the nested structure for the goal object.
        If the user mentions a weight measurement such as "I weighed 200 lb today" or "my weight is 200 lbs",
        include it as a weight_log entry with the observed value, unit, and the best available timestamp.
        reference_time: {logged_at.isoformat()}
        """,
    )

    analysis_payload = (
        f"reference_time: {logged_at.isoformat()}\n"
        f"User said: {user_text}\n"
        f"Coach responded: {ai_response}"
    )

    response = extractor_model.generate_content(
        analysis_payload,
        generation_config={
            "response_mime_type": "application/json",
        },
    )

    data = json.loads(response.text)
    profile_model = UserProfile(**data)
    return _model_dump(profile_model)


def create_or_update_user_profile(
    existing_profile: dict[str, Any] | None,
    user_text: str,
    ai_response: str,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """
    Merge newly extracted profile fields into an existing profile.
    Existing values are preserved unless the new payload overrides them.
    """
    parsed_profile = extract_structured_user_profile(
        user_text=user_text,
        ai_response=ai_response,
        reference_time=reference_time,
    )

    merged_profile = dict(existing_profile or {})
    for key, value in parsed_profile.items():
        if key == "goal" and isinstance(value, dict):
            existing_goal = merged_profile.get("goal") or {}
            if isinstance(existing_goal, dict):
                merged_goal = dict(existing_goal)
                if isinstance(value.get("weight_log"), list):
                    existing_weight_logs = existing_goal.get("weight_log") or []
                    new_weight_logs = [
                        item for item in value.get("weight_log", []) if item is not None
                    ]
                    merged_goal["weight_log"] = [
                        *existing_weight_logs,
                        *new_weight_logs,
                    ]
                for inner_key, inner_value in value.items():
                    if inner_key != "weight_log":
                        merged_goal[inner_key] = inner_value
                merged_profile["goal"] = merged_goal
            else:
                merged_profile["goal"] = value
        else:
            merged_profile[key] = value

    return merged_profile


def persist_profile_update(
    phone_number: str,
    user_text: str,
    ai_response: str,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """
    Parse the chat exchange and persist the resulting profile update
    using the existing JSON storage helpers.
    """
    from .utils import get_user_record, update_user_profile

    record = get_user_record(phone_number)
    existing_profile = record.get("user_profile", {})
    merged_profile = create_or_update_user_profile(
        existing_profile=existing_profile,
        user_text=user_text,
        ai_response=ai_response,
        reference_time=reference_time,
    )
    return update_user_profile(phone_number, merged_profile)