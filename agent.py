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
def build_initial_workflow_state() -> dict[str, Any]:
    request = blank_request()
    validation = validate_required_booking_fields(request)
    recommendation = initial_recommendation()
    availability = apply_availability_and_pricing_rules(request, validation, recommendation)
    checklist = generate_booking_checklist(request, recommendation, availability)
    packet = build_booking_packet(request, validation, recommendation, availability, checklist)
    return {
        "guest_request": request,
        "field_validation": validation,
        "room_recommendation": recommendation,
        "availability_decision": availability,
        "booking_checklist": checklist,
        "booking_packet": packet,
        "final_markdown": packet["markdown"],
    }
def _content(text: str) -> genai_types.Content:
    return genai_types.Content(role="model", parts=[genai_types.Part(text=text)])

def _state_event(author: str, text: str, updates: dict[str, Any]) -> Event:
    return Event(
        author=author, #this indicate the agent name that generated the event
        content=_content(text),
        actions=EventActions(state_delta=updates),
    )
class FinalPacketNode(FunctionNode):
    """Function node that emits the final booking packet Markdown."""

    @override
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        result = self.handler(ctx)
        updates = {self.output_key: result, "final_markdown": result["markdown"]}
        ctx.session.state.update(updates)
        yield _state_event(self.name, result["markdown"], updates)

def _validate_handler(ctx: InvocationContext) -> dict[str, Any]:
    return validate_required_booking_fields(ctx.session.state.get("guest_request"))


def _availability_handler(ctx: InvocationContext) -> dict[str, Any]:
    return apply_availability_and_pricing_rules(
        ctx.session.state.get("guest_request"),
        ctx.session.state.get("field_validation"),
        ctx.session.state.get("room_recommendation"),
    )