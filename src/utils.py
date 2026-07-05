import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = PROJECT_ROOT / "whatsapp_history.json"

DEFAULT_USER_PROFILE = {
    "name": None,
    "tdee_target": None,
    "protein_target_g": None,
    "goal": None,
    "net_carb_target_g": None,
    "fat_target_g": None,
}


def _default_user_record() -> dict[str, Any]:
    return {
        "user_profile": deepcopy(DEFAULT_USER_PROFILE),
        "chat_history": [],
        "nutrition_logs": [],
    }


def _load_all_data() -> dict[str, Any]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not parse {HISTORY_FILE}. Fix the JSON before saving new messages."
        ) from exc


def _save_all_data(data: dict[str, Any]) -> None:
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=4)


def _normalize_user_record(record: Any) -> dict[str, Any]:
    """Migrate legacy chat-only arrays to the full user record schema."""
    if isinstance(record, list):
        normalized = _default_user_record()
        normalized["chat_history"] = record
        return normalized

    if not isinstance(record, dict):
        return _default_user_record()

    normalized = _default_user_record()
    normalized["user_profile"] = {
        **DEFAULT_USER_PROFILE,
        **record.get("user_profile", {}),
    }
    normalized["chat_history"] = record.get("chat_history", [])
    normalized["nutrition_logs"] = record.get("nutrition_logs", [])
    return normalized


def _get_user_record(data: dict[str, Any], phone_number: str) -> dict[str, Any]:
    if phone_number not in data:
        return _default_user_record()
    return _normalize_user_record(data[phone_number])


def get_user_record(phone_number: str) -> dict[str, Any]:
    """Return the full stored record for a phone number."""
    data = _load_all_data()
    return _get_user_record(data, phone_number)


def load_user_history(phone_number: str) -> list:
    """Load chat history for Gemini from the user's stored record."""
    return get_user_record(phone_number)["chat_history"]


def load_user_profile(phone_number: str) -> dict[str, Any]:
    """Load profile fields such as name and macro targets."""
    return get_user_record(phone_number)["user_profile"]


def load_nutrition_logs(phone_number: str) -> list:
    """Load all nutrition log entries for a phone number."""
    return get_user_record(phone_number)["nutrition_logs"]


def update_user_profile(phone_number: str, profile_updates: dict[str, Any]) -> dict[str, Any]:
    """Merge profile updates into the stored user profile."""
    data = _load_all_data()
    record = _get_user_record(data, phone_number)
    record["user_profile"].update(profile_updates)
    data[phone_number] = record
    _save_all_data(data)
    return record["user_profile"]


def save_to_history(phone_number: str, user_msg: str, ai_msg: str) -> None:
    """Append a user/model exchange to chat_history."""
    data = _load_all_data()
    record = _get_user_record(data, phone_number)
    record["chat_history"].append({"role": "user", "parts": [user_msg]})
    record["chat_history"].append({"role": "model", "parts": [ai_msg]})
    data[phone_number] = record
    _save_all_data(data)


def save_nutrition_log(phone_number: str, log_entry: dict[str, Any]) -> None:
    """Append a structured nutrition log entry for a phone number."""
    data = _load_all_data()
    record = _get_user_record(data, phone_number)
    record["nutrition_logs"].append(log_entry)
    data[phone_number] = record
    _save_all_data(data)
