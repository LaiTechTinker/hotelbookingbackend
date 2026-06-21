from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
# this is the list of room types that the hotel offers which i used
RoomTypes=Literal[
    "standard_single",
    "standard_double",
    "deluxe_double",
    "suite",
    "family_room",
    "executive_room",
    "penthouse",
]
# this defined the status of intake form, whether it is valid or missing some information
IntakeStatus = Literal["valid", "missing_info"] 
# the following is the schema for booking status
BookingStatus = Literal[
    "pending",
    "confirmed",
    "modified",
    "cancelled",
    "awaiting_payment",
]
# this is the schema i defined to which agent uses for decisoion making,it can be used by agent to route the next decsion
RoutingDecision = Literal[
    "booking_confirmed",
    "awaiting_payment",
    "needs_more_info",
    "send_to_agent",
    "modification_requested",
]
# this is schema for room availablilty status
Availability = Literal["available", "limited", "unavailable"]

class GuestRequest(BaseModel):
    name:str=Field(description="The full name of the guest making booking request ")
    contact_method: str = Field(description="Best phone number or email to reach the guest.")
    check_in_date: str = Field(description="Requested check-in date.")
    check_out_date: str = Field(description="Requested check-out date.")
    num_nights: Optional[int] = Field(default=None, description="Number of nights derived from dates.")
    num_guests: Optional[int] = Field(default=None, description="Total number of guests.")
    room_preference: str = Field(description="Expressed room type preference or requirements.")
    special_requests: list[str] = Field(default_factory=list, description="Any special requests or amenities.")
    budget_per_night_usd: Optional[float] = Field(default=None, description="Stated budget per night in USD.")
    loyalty_number: str = Field(default="not specified", description="Loyalty or membership number if provided.")
    purpose_of_stay: str = Field(default="not specified", description="Business, leisure, honeymoon, event, etc.")
    missing_or_uncertain_facts: list[str] = Field(default_factory=list)
    raw_summary: str = Field(description="Short factual summary of the guest's request.")

class FieldValidation(BaseModel):
    missing_fields:list[str]=Field(default_factory=list, description="List of any missing required fields.")
    intake_status:IntakeStatus=Field(description="Overall status of the intake form based on field validation.")
    warnings:list[str]=Field(default_factory=list, description="Any warnings about potential issues with the provided information.")
    ready_for_booking:bool=Field(description="Indicates if the request is ready to proceed to booking based on field validation.")

class RoomRecommendation(BaseModel):
    """LLM-generated room type recommendation and pricing."""

    recommended_room_type: RoomTypes
    recommendation_rationale: str
    alternative_room_types: list[RoomTypes] = Field(default_factory=list)
    estimated_price_per_night_usd: float
    estimated_total_usd: Optional[float] = Field(default=None)
    amenities_highlight: list[str] = Field(default_factory=list)
    upsell_suggestion: Optional[str] = Field(default=None)
# this is the schema for the finding from availability, policy, or pricing rules, which can be used by agent to make decision on how to proceed with the booking
class AvailabilityRuleFinding(BaseModel):
    """Deterministic finding from availability, policy, or pricing rules."""

    rule_id: str
    message: str #this is the message sent to the user to explain the finding
    action: Literal[
        "confirm_availability",
        "suggest_alternative",
        "request_deposit",
        "collect_info",
        "escalate_to_agent",
        "apply_discount",
    ]
    detail: Optional[str] = None #An optional structured payload — anything too technical or verbose for message. Used for computed values, links, or data the next pipeline node needs.

class AvailabilityDecision(BaseModel):
    """Deterministic availability and pricing decision."""

    routing_decision: RoutingDecision
    availability: Availability
    room_type: RoomTypes
    price_per_night_usd: float
    total_price_usd: Optional[float] = Field(default=None)
    deposit_required_usd: Optional[float] = Field(default=None)
    payment_link: Optional[str] = Field(default=None)
    findings: list[AvailabilityRuleFinding] = Field(default_factory=list)
    audit_trail: list[str] = Field(default_factory=list) #A chronological log of every decision step taken inside ApplyAvailabilityAndPricing. Useful for debugging and support tickets — tells you exactly what the node did and in what order.
    policies_applied: list[str] = Field(default_factory=list)
    """
    A clean list of just the rule IDs that fired — a lightweight summary of findings for quick inspection without parsing full finding objects.
    # Two rules fired
policies_applied = ["PRICE-001", "DEP-001"]

# Late booking, full prepayment
policies_applied = ["PRICE-001", "LATE-001"]
    """

class BookingChecklistItem(BaseModel):
    """One guest-facing action item."""

    item: str
    reason: str
    priority: Literal["required", "recommended", "optional"]
    completed: bool = False

class BookingChecklist(BaseModel):
    """Checklist for completing the booking."""

    items: list[BookingChecklistItem] = Field(default_factory=list)
    guest_tip: str
    
class BookingPacket(BaseModel):
    """Final booking summary returned to the UI."""

    room_type: RoomTypes
    intake_status: IntakeStatus
    booking_status: BookingStatus
    routing_decision: RoutingDecision
    missing_information: list[str] = Field(default_factory=list)
    checklist: list[BookingChecklistItem] = Field(default_factory=list)
    price_per_night_usd: float
    total_price_usd: Optional[float] = Field(default=None)
    deposit_required_usd: Optional[float] = Field(default=None)
    payment_link: Optional[str] = Field(default=None)
    availability: Availability
    guest_next_message: str
    concierge_handoff_summary: str
    audit_trail: list[str] = Field(default_factory=list)
    markdown: str


