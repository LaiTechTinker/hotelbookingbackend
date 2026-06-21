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

def _checklist_handler(ctx: InvocationContext) -> dict[str, Any]:
    return generate_booking_checklist(
        ctx.session.state.get("guest_request"),
        ctx.session.state.get("room_recommendation"),
        ctx.session.state.get("availability_decision"),
    )


def _final_packet_handler(ctx: InvocationContext) -> dict[str, Any]:
    return build_booking_packet(
        ctx.session.state.get("guest_request"),
        ctx.session.state.get("field_validation"),
        ctx.session.state.get("room_recommendation"),
        ctx.session.state.get("availability_decision"),
        ctx.session.state.get("booking_checklist"),
    )

# ── LLM Agents ────────────────────────────────────────────────────────────────

def create_extractor() -> LlmAgent:
    return LlmAgent(
        name="ExtractGuestRequest",
        model=MODEL,
        description="Extracts structured booking intent from a guest's natural language request.",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        instruction="""
You are the intake specialist for a hotel booking AI agent.

Read the guest's message and extract structured booking details into a GuestRequest.
Preserve facts exactly. Do not invent names, dates, phone numbers, or prices.

Extraction rules:
- guest_name: full name if provided, otherwise "not specified".
- contact_method: phone or email if provided, otherwise "not specified".
- check_in_date: check-in date in human-readable form, otherwise "not specified".
- check_out_date: check-out date, otherwise "not specified".
- num_nights: compute from dates if possible, else null.
- num_guests: total number of guests if stated, else null.
- room_preference: any room type keywords (suite, double, family, quiet, sea view, etc.).
- special_requests: list any extras (airport transfer, extra bed, early check-in, dietary needs, etc.).
- budget_per_night_usd: numeric USD budget only if the guest explicitly states one.
- loyalty_number: membership or loyalty number if mentioned.
- purpose_of_stay: business, honeymoon, vacation, anniversary, conference, etc. if mentioned.
- missing_or_uncertain_facts: key facts that are vague, missing, or contradictory.
- raw_summary: one concise sentence summarizing the request.

Do not confirm prices, availability, or payment. This is extraction only.
""",
        output_schema=GuestRequest,
        output_key="guest_request",
    )


def create_recommender() -> LlmAgent:
    return LlmAgent(
        name="RecommendRoomType",
        model=MODEL,
        description="Recommends the best room type and highlights amenities based on the guest's request.",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        instruction="""
You are a hotel concierge AI. Recommend the best room for this guest.

Guest request:
{guest_request}

Validation:
{field_validation}

Available room types with base prices (USD/night):
- standard_single: $89 — solo traveler, work desk, WiFi.
- standard_double: $119 — couples or friends, queen bed, mini-fridge.
- deluxe_double: $159 — couples wanting luxury, city view, bathtub, mini-bar.
- suite: $249 — small groups or luxury seekers, separate living area, kitchenette, butler.
- family_room: $189 — families, two queen beds, up to 4 guests.
- executive_room: $209 — business travelers, lounge access, business center.
- penthouse: $549 — top-floor, panoramic views, private terrace, full kitchen, jacuzzi.

Selection rules:
- Match room capacity to num_guests.
- Respect stated budget.
- Business stay → prefer executive_room or suite.
- Honeymoon/anniversary → prefer deluxe_double or suite.
- Family → prefer family_room.
- Solo → standard_single.
- Include 1-2 alternative room types.
- Suggest an upsell if appropriate (e.g., "add breakfast package for $22/night").

Return only the structured RoomRecommendation. Do not confirm availability.
""",
        output_schema=RoomRecommendation,
        output_key="room_recommendation",
    )


def create_workflow() -> SequentialAgent:
    return SequentialAgent(
        name=APP_NAME,
        description="End-to-end hotel booking agent: extraction → validation → recommendation → availability → checklist → packet.",
        sub_agents=[
            create_extractor(),
            FunctionNode(
                name="ValidateBookingFields",
                description="Validates required booking fields deterministically.",
                handler=_validate_handler,
                output_key="field_validation",
                summary="Validated required booking fields.",
            ),
            create_recommender(),
            FunctionNode(
                name="ApplyAvailabilityAndPricing",
                description="Applies availability simulation, seasonal pricing, deposit, and routing rules.",
                handler=_availability_handler,
                output_key="availability_decision",
                summary="Applied availability and pricing rules.",
            ),
            FunctionNode(
                name="GenerateBookingChecklist",
                description="Builds a guest-facing action checklist.",
                handler=_checklist_handler,
                output_key="booking_checklist",
                summary="Generated booking checklist.",
            ),
            FinalPacketNode(
                name="FinalBookingPacket",
                description="Builds the final polished Markdown booking packet.",
                handler=_final_packet_handler,
                output_key="booking_packet",
                summary="Built final booking packet.",
            ),
        ],
    )


root_agent = create_workflow()


async def run_booking_workflow(
    guest_transcript: str,
    *,
    session_id: str | None = None,
    user_id: str = "live-ui",
) -> dict[str, Any]:
    """Run the ADK booking graph for the current guest transcript snapshot."""

    transcript = str(guest_transcript or "").strip()
    if not transcript:
        return build_initial_workflow_state()

    adk_session_id = f"booking-{session_id or uuid.uuid4().hex}"
    session_service = InMemorySessionService()
    await _await_if_needed(
        session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=adk_session_id,
        )
    )
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service,
    )
    message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=(
            "Use this full guest transcript as the source of truth for the hotel booking workflow. "
            "Do not invent missing facts.\n\n" + transcript
        ))],
    )

    event_count = 0
    async for _event in runner.run_async(
        user_id=user_id,
        session_id=adk_session_id,
        new_message=message,
    ):
        event_count += 1
    if event_count == 0:
        raise RuntimeError("ADK workflow completed without emitting any events.")

    session = await _await_if_needed(
        session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=adk_session_id,
        )
    )
    state = session.state
    request = GuestRequest.model_validate(_plain(state.get("guest_request")))
    validation = FieldValidation.model_validate(_plain(state.get("field_validation")))
    recommendation = RoomRecommendation.model_validate(_plain(state.get("room_recommendation")))
    availability = AvailabilityDecision.model_validate(_plain(state.get("availability_decision")))
    checklist = BookingChecklist.model_validate(_plain(state.get("booking_checklist")))
    packet = BookingPacket.model_validate(_plain(state.get("booking_packet")))

    return {
        "guest_request": request.model_dump(exclude_none=True),
        "field_validation": validation.model_dump(exclude_none=True),
        "room_recommendation": recommendation.model_dump(exclude_none=True),
        "availability_decision": availability.model_dump(exclude_none=True),
        "booking_checklist": checklist.model_dump(exclude_none=True),
        "booking_packet": packet.model_dump(exclude_none=True),
        "final_markdown": packet.markdown,
    }


__all__ = [
    "APP_NAME",
    "MODEL",
    "blank_request",
    "build_initial_workflow_state",
    "run_booking_workflow",
    "root_agent",
]
