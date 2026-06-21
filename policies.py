"""Deterministic hotel booking policies, availability rules, pricing, and packet builders."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from .schema import (
        AvailabilityDecision,
        AvailabilityRuleFinding,
        BookingChecklist,
        BookingChecklistItem,
        BookingPacket,
        FieldValidation,
        GuestRequest,
        RoomRecommendation,
    )
ROOM_CATALOG: dict[str, dict] = {
    "standard_single": {
        "name": "Standard Single",
        "base_price": 89.0,
        "capacity": 1,
        "amenities": ["Free WiFi", "Air conditioning", "Smart TV", "Work desk"],
        "description": "Comfortable room for solo travelers.",
    },
    "standard_double": {
        "name": "Standard Double",
        "base_price": 119.0,
        "capacity": 2,
        "amenities": ["Free WiFi", "Air conditioning", "Smart TV", "Mini-fridge"],
        "description": "Spacious room with a queen-size bed.",
    },
    "deluxe_double": {
        "name": "Deluxe Double",
        "base_price": 159.0,
        "capacity": 2,
        "amenities": ["Free WiFi", "Air conditioning", "Smart TV", "Bathtub", "City view", "Mini-bar"],
        "description": "Premium room with city views and luxury bath.",
    },
    "suite": {
        "name": "Suite",
        "base_price": 249.0,
        "capacity": 3,
        "amenities": ["Free WiFi", "Separate living area", "Kitchenette", "Premium bath", "Butler service"],
        "description": "Luxury suite with separate living and sleeping areas.",
    },
    "family_room": {
        "name": "Family Room",
        "base_price": 189.0,
        "capacity": 4,
        "amenities": ["Free WiFi", "Two queen beds", "Air conditioning", "Smart TV", "Mini-fridge"],
        "description": "Ideal for families with two queen beds.",
    },
    "executive_room": {
        "name": "Executive Room",
        "base_price": 209.0,
        "capacity": 2,
        "amenities": ["Free WiFi", "Executive lounge access", "Business center", "Bathrobe", "Premium toiletries"],
        "description": "Business-class room with executive lounge access.",
    },
    "penthouse": {
        "name": "Penthouse",
        "base_price": 549.0,
        "capacity": 4,
        "amenities": ["Free WiFi", "Private terrace", "Panoramic views", "Private butler", "Full kitchen", "Jacuzzi"],
        "description": "Top-floor penthouse with panoramic city views.",
    },
}
BLOCKING_FIELD_QUESTIONS = {
    "guest_name": "What is your full name for the reservation?",
    "contact_method": "What is the best email or phone number to reach you?",
    "check_in_date": "What date would you like to check in?",
    "check_out_date": "What date would you like to check out?",
    "num_guests": "How many guests will be staying?",
}
# 
DEPOSIT_THRESHOLD_NIGHTS = 3 #this means that if number of days before checking>=3 it requires upfront deposit
DEPOSIT_PERCENT = 0.30 #ppercentage of checking deposit
LATE_BOOKING_DAYS = 2 #this overid upfront deposit and requires full payment
# this is the seasonal range constant that determines the price of room at certain season
"""
example :
((12, 20), (1, 5),  1.45)  # Dec 20 → Jan 5:  base price × 1.45  (+45%)
((6, 15),  (8, 31), 1.25)  # Jun 15 → Aug 31: base price × 1.25  (+25%)
((4, 1),   (4, 30), 1.15)  # Apr 1  → Apr 30: base price × 1.15  (+15%)

"""
SEASONAL_MULTIPLIERS: list[tuple[tuple[int, int], tuple[int, int], float]] = [
    ((12, 20), (1, 5), 1.45),   # Christmas/New Year peak
    ((6, 15), (8, 31), 1.25),   # Summer peak
    ((4, 1), (4, 30), 1.15),    # Spring break
]
# this code block converts any input value either in json format of string format to proper pydantic base model type

def _as_model(model_type, value):
    if isinstance(value, model_type):
        return value
    if value is None:
        return model_type()
    if isinstance(value, str):
        return model_type.model_validate_json(value)
    return model_type.model_validate(value)

# this util function check if user input value is either empty,na,or not specified and return a boolen val
def _blank(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"", "unknown", "not specified", "unspecified", "n/a", "none", "not provided"}

# this function takes raw data input from user and convert it to standard date format and returns none if no date is provided
def _parse_dates(value:str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text, flags=re.IGNORECASE)
    candidates = [cleaned[:10], cleaned]
    formats = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"]
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None
def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result

def _seasonal_multiplier(check_in: datetime | None) -> float:
    if not check_in:
        return 1.0
    for (sm, sd), (em, ed), mult in SEASONAL_MULTIPLIERS:
        start = check_in.replace(month=sm, day=sd)
        end_year = check_in.year + (1 if em < sm else 0)
        end = check_in.replace(year=end_year, month=em, day=ed)
        if start <= check_in <= end:
            return mult
    return 1.0
def _simulate_availability(room_type: str, check_in: datetime | None) -> str:
    """Simple deterministic availability simulation based on room type + date hash."""
    if check_in is None:
        return "available"
    seed = (check_in.day + check_in.month + len(room_type)) % 10
    if room_type == "penthouse":
        return "available" if seed < 4 else "limited"
    if room_type == "suite":
        return "available" if seed < 6 else "limited"
    return "available" if seed < 8 else "limited"


def _generate_payment_link(guest_name: str, room_type: str, total: float) -> str:
    safe_name = re.sub(r"\W+", "", guest_name.lower())
    safe_room = room_type.replace("_", "-")
    return f"https://pay.grandhotel.example/booking?guest={safe_name}&room={safe_room}&amount={total:.2f}"


def validate_required_booking_fields(request_value: Any) -> dict[str, Any]:
    """Validate that the minimum booking fields are present."""
    request = _as_model(GuestRequest, request_value) if request_value else GuestRequest(
        guest_name="not specified", contact_method="not specified",
        check_in_date="not specified", check_out_date="not specified",
        room_preference="not specified", raw_summary="",
    )

    missing: list[str] = []
    warnings: list[str] = []

    for field in ["guest_name", "contact_method", "check_in_date", "check_out_date"]:
        if _blank(getattr(request, field, "")):
            missing.append(field)

    if request.num_guests is None:
        missing.append("num_guests")

    check_in = _parse_dates(request.check_in_date)
    check_out = _parse_dates(request.check_out_date)

    if check_in and check_out:
        if check_out <= check_in:
            warnings.append("Check-out date must be after check-in date.")
        if check_in < datetime.now() - timedelta(days=1):
            warnings.append("Check-in date appears to be in the past.")
    validation = FieldValidation(
        intake_status="valid" if not missing else "missing_info",
        missing_fields=missing,
        warnings=warnings,
        ready_for_booking=len(missing) == 0 and len(warnings) == 0,
    )
    return validation.model_dump(exclude_none=True) #this converts the pydatic model class to json and leaves out any field that is none

def apply_availability_and_pricing_rules(
    request_value: Any,
    validation_value: Any,
    recommendation_value: Any,
) -> dict[str, Any]:
    """Deterministic availability check, pricing, and routing."""
    request = _as_model(GuestRequest, request_value) if request_value else GuestRequest(
        guest_name="", contact_method="", check_in_date="", check_out_date="",
        room_preference="", raw_summary="",
    )
    validation = _as_model(FieldValidation, validation_value)
    recommendation = _as_model(RoomRecommendation, recommendation_value)

    findings: list[AvailabilityRuleFinding] = []
    audit: list[str] = []
    policies: list[str] = []

    room_type = recommendation.recommended_room_type
    catalog_entry = ROOM_CATALOG.get(room_type, ROOM_CATALOG["standard_double"])
    base_price = catalog_entry["base_price"]

    check_in = _parse_dates(request.check_in_date)
    check_out = _parse_dates(request.check_out_date)
    num_nights = request.num_nights or (
        (check_out - check_in).days if check_in and check_out else None
    )

    # Seasonal pricing
    multiplier = _seasonal_multiplier(check_in)
    adjusted_price = round(base_price * multiplier, 2)
    if multiplier > 1.0:
        findings.append(AvailabilityRuleFinding(
            rule_id="PRICE-001",
            message=f"Seasonal rate applied: {multiplier:.2f}× base price.",
            action="confirm_availability",
            detail=f"Peak season surcharge: base ${base_price:.2f} → ${adjusted_price:.2f}/night",
        ))
        policies.append(f"Seasonal multiplier: {multiplier:.2f}×")
        audit.append(f"Seasonal rate {multiplier:.2f}× applied to {room_type}.")

    # Availability simulation
    availability = _simulate_availability(room_type, check_in)
    if availability == "limited":
        findings.append(AvailabilityRuleFinding(
            rule_id="AVAIL-001",
            message=f"{catalog_entry['name']} has limited availability for your dates.",
            action="suggest_alternative",
            detail="Consider booking immediately or exploring an alternative room type.",
        ))
        audit.append(f"Limited availability detected for {room_type}.")
    else:
        audit.append(f"Room {room_type} is available for requested dates.")

    # Guest capacity check
    if request.num_guests and request.num_guests > catalog_entry["capacity"]:
        alt = next(
            (k for k, v in ROOM_CATALOG.items() if v["capacity"] >= request.num_guests and k != room_type),
            "family_room",
        )
        findings.append(AvailabilityRuleFinding(
            rule_id="CAP-001",
            message=f"Selected room holds {catalog_entry['capacity']} guests; {request.num_guests} requested.",
            action="suggest_alternative",
            detail=f"Suggested upgrade: {ROOM_CATALOG[alt]['name']}",
        ))
        audit.append(f"Capacity mismatch: {room_type} max {catalog_entry['capacity']}, guest needs {request.num_guests}.")

    # Total price
    total_price = round(adjusted_price * num_nights, 2) if num_nights else None

    # Deposit rule
    deposit = None
    if num_nights and num_nights >= DEPOSIT_THRESHOLD_NIGHTS:
        deposit = round((total_price or adjusted_price * DEPOSIT_THRESHOLD_NIGHTS) * DEPOSIT_PERCENT, 2)
        findings.append(AvailabilityRuleFinding(
            rule_id="DEP-001",
            message=f"A {int(DEPOSIT_PERCENT * 100)}% deposit is required for stays of {DEPOSIT_THRESHOLD_NIGHTS}+ nights.",
            action="request_deposit",
            detail=f"Deposit amount: ${deposit:.2f}",
        ))
        policies.append(f"30% deposit required for {num_nights}-night stay.")
        audit.append(f"Deposit rule triggered: ${deposit:.2f} required.")

    # Late booking
    if check_in:
        days_until = (check_in - datetime.now()).days
        if 0 <= days_until <= LATE_BOOKING_DAYS:
            findings.append(AvailabilityRuleFinding(
                rule_id="LATE-001",
                message="Check-in is within 48 hours. Full payment may be required at booking.",
                action="request_deposit",
                detail="Late booking policy: full prepayment required.",
            ))
            policies.append("Late booking: full prepayment required.")
            audit.append("Late booking within 48 hours detected.")

    # Missing info
    if validation.missing_fields:
        findings.append(AvailabilityRuleFinding(
            rule_id="INFO-001",
            message=f"Missing required fields: {', '.join(validation.missing_fields)}.",
            action="collect_info",
        ))
        audit.append(f"Booking blocked pending missing fields: {validation.missing_fields}.")

    # Payment link
    payment_link = None
    if not validation.missing_fields and total_price:
        payment_link = _generate_payment_link(request.guest_name, room_type, deposit or total_price)
        audit.append("Payment link generated.")

    # Routing decision
    if validation.missing_fields:
        routing = "needs_more_info"
    elif availability == "unavailable":
        routing = "send_to_agent"
    elif deposit or (check_in and (check_in - datetime.now()).days <= LATE_BOOKING_DAYS):
        routing = "awaiting_payment"
    else:
        routing = "booking_confirmed"

    decision = AvailabilityDecision(
        routing_decision=routing,
        availability=availability,
        room_type=room_type,
        price_per_night_usd=adjusted_price,
        total_price_usd=total_price,
        deposit_required_usd=deposit,
        payment_link=payment_link,
        findings=findings,
        audit_trail=audit,
        policies_applied=policies,
    )
    return decision.model_dump(exclude_none=True)
def _next_guest_message(
    routing: str,
    missing: list[str],
    availability_decision: AvailabilityDecision,
) -> str:
    if routing == "needs_more_info":
        for field in missing:
            if field in BLOCKING_FIELD_QUESTIONS:
                return BLOCKING_FIELD_QUESTIONS[field]
        return "Could you please provide your check-in and check-out dates and the number of guests?"

    if routing == "awaiting_payment":
        link = availability_decision.payment_link
        deposit = availability_decision.deposit_required_usd
        total = availability_decision.total_price_usd
        amount = f"${deposit:.2f} deposit" if deposit else f"${total:.2f}" if total else "the required amount"
        return (
            f"Great news — your room is ready to book! Please complete your payment of {amount} "
            f"to confirm your reservation: {link}"
        )

    if routing == "booking_confirmed":
        return (
            f"Your reservation has been confirmed! A confirmation email will be sent to you shortly. "
            f"Check-in is at 3:00 PM. We look forward to welcoming you!"
        )

    if routing == "send_to_agent":
        return (
            "I'd like to connect you with one of our guest services specialists who can assist with "
            "your specific request. Please hold or call +1-800-GRAND-INN."
        )

    if routing == "modification_requested":
        return "Your modification request has been received. Our team will confirm the changes within 2 hours."

    return "Thank you for your inquiry. How else can I assist you?"

def build_booking_packet(
    request_value: Any,
    validation_value: Any,
    recommendation_value: Any,
    availability_value: Any,
    checklist_value: Any,
) -> dict[str, Any]:
    """Build the final Markdown booking packet."""

    request = _as_model(GuestRequest, request_value) if request_value else GuestRequest(
        guest_name="", contact_method="", check_in_date="", check_out_date="",
        room_preference="", raw_summary="",
    )
    validation = _as_model(FieldValidation, validation_value)
    recommendation = _as_model(RoomRecommendation, recommendation_value)
    availability = _as_model(AvailabilityDecision, availability_value)
    checklist_obj = _as_model(BookingChecklist, checklist_value)

    missing = _dedupe(validation.missing_fields)
    routing = availability.routing_decision
    route_label = routing.replace("_", " ").title()
    room_info = ROOM_CATALOG.get(availability.room_type, {})

    checklist_lines = [
        f"- [{'✓' if item.completed else item.priority}] **{item.item}** — {item.reason}"
        for item in checklist_obj.items
    ] or ["- No action items identified."]

    missing_lines = [f"- {f}" for f in missing] or ["- No required fields are missing."]

    finding_lines = [
        f"- `{f.rule_id}` {f.message}" for f in availability.findings
    ] or ["- No rule findings."]

    price_str = f"${availability.price_per_night_usd:.2f}/night"
    total_str = f"${availability.total_price_usd:.2f} total" if availability.total_price_usd else "TBD"
    deposit_str = f"${availability.deposit_required_usd:.2f} deposit required" if availability.deposit_required_usd else "No deposit required"
    payment_str = f"[Pay now]({availability.payment_link})" if availability.payment_link else "Not yet generated"

    concierge_summary = (
        f"{request.guest_name or 'Guest'} requested a {room_info.get('name', availability.room_type)} "
        f"from {request.check_in_date} to {request.check_out_date} "
        f"for {request.num_guests or 'unknown'} guest(s). "
        f"Purpose: {request.purpose_of_stay}. "
        f"Rate: {price_str}. {total_str}. {deposit_str}."
    )

    guest_next = _next_guest_message(routing, missing, availability)

    audit_lines = [f"{i}. {entry}" for i, entry in enumerate(availability.audit_trail, 1)]

    amenities = room_info.get("amenities", [])
    amenities_str = ", ".join(amenities) if amenities else "Standard amenities"

    markdown = f"""# Hotel Booking Summary — Grand Hotel

**Room:** {room_info.get('name', availability.room_type)}  
**Availability:** {availability.availability.title()}  
**Status:** {route_label}  
**Intake:** {validation.intake_status.replace('_', ' ').title()}

## Guest Details
- **Name:** {request.guest_name or 'Not provided'}
- **Contact:** {request.contact_method or 'Not provided'}
- **Check-in:** {request.check_in_date or 'Not specified'}
- **Check-out:** {request.check_out_date or 'Not specified'}
- **Guests:** {request.num_guests or 'Not specified'}
- **Purpose:** {request.purpose_of_stay}

## Pricing
- **Rate:** {price_str}
- **Total:** {total_str}
- **Deposit:** {deposit_str}
- **Payment:** {payment_str}

## Room Highlights
{amenities_str}

> {recommendation.recommendation_rationale}

## Missing Information
{chr(10).join(missing_lines)}

## Booking Checklist
{chr(10).join(checklist_lines)}

**Tip:** {checklist_obj.guest_tip}

## Policy Findings
{chr(10).join(finding_lines)}

## Concierge Handoff
{concierge_summary}

## Guest Next Message
{guest_next}

## Audit Trail
{chr(10).join(audit_lines)}

---
*This is an automated booking summary. All reservations are subject to availability confirmation and hotel terms.*
"""

    packet = BookingPacket(
        room_type=availability.room_type,
        intake_status=validation.intake_status,
        booking_status="awaiting_payment" if routing == "awaiting_payment" else
                       "confirmed" if routing == "booking_confirmed" else
                       "pending",
        routing_decision=routing,
        missing_information=missing,
        checklist=checklist_obj.items,
        price_per_night_usd=availability.price_per_night_usd,
        total_price_usd=availability.total_price_usd,
        deposit_required_usd=availability.deposit_required_usd,
        payment_link=availability.payment_link,
        availability=availability.availability,
        guest_next_message=guest_next,
        concierge_handoff_summary=concierge_summary,
        audit_trail=availability.audit_trail,
        markdown=markdown,
    )
    return packet.model_dump(exclude_none=True)
