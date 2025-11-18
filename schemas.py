"""
Database Schemas for Ombrellone

Each Pydantic model maps to a MongoDB collection (lowercased class name).
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import date

class BeachClub(BaseModel):
    name: str = Field(..., description="Beach club name")
    hero_image: Optional[str] = Field(None, description="Hero image URL")
    rating: float = Field(4.6, ge=0, le=5, description="Average rating")
    total_reviews: int = Field(0, ge=0)
    currency: str = Field("EUR")
    default_timeslots: List[str] = Field(
        default_factory=lambda: ["08:00-12:00", "12:00-16:00", "16:00-20:00", "Full Day"],
        description="Available booking slots"
    )
    services: List["Service"] = Field(default_factory=list, description="Optional services offered")

class Service(BaseModel):
    key: str = Field(..., description="Unique service key e.g. towel, drinks, cabin")
    name: str = Field(..., description="Display name")
    price: float = Field(..., ge=0, description="Price per slot or per day")
    billing: Literal["per_slot", "per_day"] = Field("per_slot")

class Umbrella(BaseModel):
    club_id: str = Field(..., description="Reference to beach club _id")
    number: int = Field(..., ge=1, description="Umbrella number shown on map")
    row: int = Field(..., ge=1)
    x: float = Field(..., ge=0, le=1, description="Normalized X position on map (0-1)")
    y: float = Field(..., ge=0, le=1, description="Normalized Y position on map (0-1)")
    sunbeds_included: int = Field(2, ge=0, le=6)
    base_price_slot: float = Field(15.0, ge=0)
    base_price_day: float = Field(45.0, ge=0)

class Booking(BaseModel):
    club_id: str = Field(...)
    umbrella_id: str = Field(...)
    umbrella_number: int = Field(...)
    booking_date: date = Field(..., description="YYYY-MM-DD")
    slot: str = Field(..., description="One of club timeslots")
    guests: int = Field(2, ge=1, le=8)
    services: List[str] = Field(default_factory=list, description="List of service keys")
    customer_name: str = Field(...)
    customer_email: str = Field(...)
    total_amount: float = Field(..., ge=0)
    status: Literal["pending", "confirmed", "cancelled"] = Field("pending")

class User(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    avatar: Optional[str] = None
