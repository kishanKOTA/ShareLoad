"""Enumerations shared across the API contracts (see docs/PRD.md, "Contracts").

All enums subclass ``str`` so they serialize to their plain string value in JSON
and compare equal to raw strings loaded from fixtures.
"""

from enum import Enum


class CargoType(str, Enum):
    AMBIENT = "ambient"
    REFRIGERATED = "refrigerated"
    FROZEN = "frozen"
    HAZARDOUS = "hazardous"
    FRAGILE = "fragile"
    OVERSIZED = "oversized"
    OTHER = "other"


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVALS = "pending_approvals"
    PARTIALLY_APPROVED = "partially_approved"
    APPROVED_FOR_EXTERNAL_COORDINATION = "approved_for_external_coordination"
    REJECTED = "rejected"


class ReasonCode(str, Enum):
    """Why a trip/shipment candidate failed validation."""

    CAPACITY_WEIGHT_EXCEEDED = "CAPACITY_WEIGHT_EXCEEDED"
    CAPACITY_VOLUME_EXCEEDED = "CAPACITY_VOLUME_EXCEEDED"
    CARGO_TEMP_UNSUPPORTED = "CARGO_TEMP_UNSUPPORTED"
    HAZMAT_UNSUPPORTED = "HAZMAT_UNSUPPORTED"
    TIME_WINDOW_CONFLICT = "TIME_WINDOW_CONFLICT"
    DIRECTION_MISMATCH = "DIRECTION_MISMATCH"
    DETOUR_EXCEEDS_LIMIT = "DETOUR_EXCEEDS_LIMIT"
    MISSING_CRITICAL_FIELD = "MISSING_CRITICAL_FIELD"


class TripLeg(str, Enum):
    OUTBOUND = "outbound"
    RETURN = "return"
