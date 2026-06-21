"""ADK hybrid graph workflow for the Hotel Booking Agent."""

from __future__ import annotations

import inspect
import json
import uuid
from typing import Any, AsyncGenerator, Callable

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pydantic import BaseModel, ConfigDict
from typing_extensions import override

from .policies import (
        apply_availability_and_pricing_rules,
        build_booking_packet,
        generate_booking_checklist,
        validate_required_booking_fields,
    )
from .schema import (
        AvailabilityDecision,
        BookingChecklist,
        BookingPacket,
        FieldValidation,
        GuestRequest,
        RoomRecommendation,
    )
MODEL = "gemini-3.0-flash-live-preview"
APP_NAME = "Lai Agent"

async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value

def blank_request() -> dict[str, Any]:
    return {
        "guest_name": "not specified",
        "contact_method": "not specified",
        "check_in_date": "not specified",
        "check_out_date": "not specified",
        "num_nights": None,
        "num_guests": None,
        "room_preference": "not specified",
        "special_requests": [],
        "budget_per_night_usd": None,
        "loyalty_number": "not specified",
        "purpose_of_stay": "not specified",
        "missing_or_uncertain_facts": [],
        "raw_summary": "not specified",
    }

def initial_recommendation() -> dict[str, Any]:
    return {
        "recommended_room_type": "standard_double",
        "recommendation_rationale": "Awaiting guest preferences.",
        "alternative_room_types": [],
        "estimated_price_per_night_usd": 119.0,
        "amenities_highlight": [],
        "upsell_suggestion": None,
    }