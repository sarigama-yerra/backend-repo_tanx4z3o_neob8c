import os
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import BeachClub, Umbrella, Booking, Service

app = FastAPI(title="Ombrellone API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"name": "Ombrellone API", "status": "ok"}


# Helper
def collection_name(model_cls) -> str:
    return model_cls.__name__.lower()


# Bootstrap demo data if empty (idempotent)
@app.on_event("startup")
async def bootstrap():
    if db is None:
        return
    clubs = list(db[collection_name(BeachClub)].find({}))
    if not clubs:
        club = BeachClub(
            name="Lido Mare Blu",
            hero_image="https://images.unsplash.com/photo-1500375592092-40eb2168fd21?q=80&w=1600&auto=format&fit=crop",
            rating=4.7,
            total_reviews=324,
            services=[
                Service(key="towel", name="Beach Towel", price=3.0, billing="per_day"),
                Service(key="drinks", name="Welcome Drink", price=5.0, billing="per_slot"),
                Service(key="cabin", name="Private Cabin", price=12.0, billing="per_day"),
            ],
        )
        club_id = db[collection_name(BeachClub)].insert_one(club.model_dump()).inserted_id

        # Create a small grid of umbrellas for demo
        umbrellas = []
        idx = 1
        for row in range(1, 5):
            for col in range(1, 9):
                umbrellas.append(
                    Umbrella(
                        club_id=str(club_id),
                        number=idx,
                        row=row,
                        x=col / 9.0,
                        y=row / 6.0,
                        sunbeds_included=2,
                        base_price_slot=15 + row * 2,
                        base_price_day=45 + row * 5,
                    ).model_dump()
                )
                idx += 1
        if umbrellas:
            db[collection_name(Umbrella)].insert_many(umbrellas)


class AvailabilityResponse(BaseModel):
    umbrella_id: str
    number: int
    status: str  # available | occupied | reserved


@app.get("/api/club")
async def get_club():
    club = db[collection_name(BeachClub)].find_one({})
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    club["_id"] = str(club["_id"])  # stringify
    return club


@app.get("/api/map")
async def get_map():
    club = db[collection_name(BeachClub)].find_one({})
    if not club:
        raise HTTPException(404, "Club not found")
    umbrellas = list(db[collection_name(Umbrella)].find({"club_id": str(club["_id"])}))
    for u in umbrellas:
        u["_id"] = str(u["_id"])  # stringify for frontend
    return {"umbrellas": umbrellas}


@app.get("/api/availability")
async def availability(
    booking_date: str = Query(..., description="YYYY-MM-DD"),
    slot: str = Query("Full Day")
):
    try:
        _ = date.fromisoformat(booking_date)
    except Exception:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

    club = db[collection_name(BeachClub)].find_one({})
    if not club:
        raise HTTPException(404, "Club not found")

    umbrellas = list(db[collection_name(Umbrella)].find({"club_id": str(club["_id"])}))

    # Get bookings for that date+slot
    bookings = db[collection_name(Booking)].find({
        "booking_date": booking_date,
        "slot": slot,
        "status": {"$in": ["pending", "confirmed"]},
    })
    occupied_ids = {b["umbrella_id"] for b in bookings}

    result: List[AvailabilityResponse] = []
    for u in umbrellas:
        status = "available" if str(u["_id"]) not in occupied_ids else "occupied"
        result.append({"umbrella_id": str(u["_id"]), "number": u["number"], "status": status})
    return {"date": booking_date, "slot": slot, "availability": result}


class PriceQuote(BaseModel):
    base: float
    extras: List[Dict[str, Any]]
    total: float


@app.post("/api/quote")
async def quote(payload: Dict[str, Any]):
    umbrella_id = payload.get("umbrella_id")
    slot = payload.get("slot", "Full Day")
    services = payload.get("services", [])

    u = db[collection_name(Umbrella)].find_one({"_id": {"$eq": db.get_collection(collection_name(Umbrella)).database.client.get_database().client.get_default_database()}})
    u = db[collection_name(Umbrella)].find_one({"_id": {"$exists": True}})

    from bson import ObjectId
    try:
        u = db[collection_name(Umbrella)].find_one({"_id": ObjectId(umbrella_id)})
    except Exception:
        raise HTTPException(404, "Umbrella not found")

    if not u:
        raise HTTPException(404, "Umbrella not found")

    base = u["base_price_day"] if slot == "Full Day" else u["base_price_slot"]

    club = db[collection_name(BeachClub)].find_one({"_id": db[collection_name(BeachClub)].find_one({})["_id"]})

    extras = []
    total = base
    for s_key in services:
        svc = next((s for s in club.get("services", []) if s.get("key") == s_key), None)
        if svc:
            price = svc["price"]
            if svc.get("billing") == "per_slot" and slot == "Full Day":
                price *= 2  # naive: full day = 2 slots
            total += price
            extras.append({"key": s_key, "name": svc["name"], "price": price})

    return PriceQuote(base=base, extras=extras, total=total)


class BookingRequest(BaseModel):
    umbrella_id: str
    umbrella_number: int
    booking_date: str
    slot: str
    guests: int = 2
    services: List[str] = []
    customer_name: str
    customer_email: str


@app.post("/api/book")
async def create_booking(req: BookingRequest):
    # Check already booked
    exists = db[collection_name(Booking)].find_one({
        "umbrella_id": req.umbrella_id,
        "booking_date": req.booking_date,
        "slot": req.slot,
        "status": {"$in": ["pending", "confirmed"]},
    })
    if exists:
        raise HTTPException(409, "Umbrella already booked for selected time")

    # Price quote
    quote_resp = await quote({
        "umbrella_id": req.umbrella_id,
        "slot": req.slot,
        "services": req.services,
    })

    # Persist booking (payment integration would be here; mark pending)
    club = db[collection_name(BeachClub)].find_one({})
    booking = Booking(
        club_id=str(club["_id"]),
        umbrella_id=req.umbrella_id,
        umbrella_number=req.umbrella_number,
        booking_date=date.fromisoformat(req.booking_date),
        slot=req.slot,
        guests=req.guests,
        services=req.services,
        customer_name=req.customer_name,
        customer_email=req.customer_email,
        total_amount=quote_resp.total,
        status="confirmed",  # demo: immediately confirmed
    )

    bid = create_document(collection_name(Booking), booking)

    return {
        "booking_id": bid,
        "status": "confirmed",
        "quote": quote_resp.model_dump(),
    }


@app.get("/api/bookings")
async def list_bookings(email: Optional[str] = None):
    flt = {"customer_email": email} if email else {}
    bookings = get_documents(collection_name(Booking), flt)
    # stringify datatypes
    for b in bookings:
        b["_id"] = str(b["_id"]) if "_id" in b else None
        if isinstance(b.get("booking_date"), (datetime, date)):
            b["booking_date"] = b["booking_date"].isoformat()
    return {"items": bookings}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available" if db is None else "✅ Connected",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "collections": []
    }
    try:
        if db is not None:
            response["collections"] = db.list_collection_names()[:10]
    except Exception as e:
        response["database"] = f"⚠️ {str(e)[:60]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
