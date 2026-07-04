import httpx
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db
from auth_utils import get_current_user, now_iso


router = APIRouter(
    prefix="/api/location",
    tags=["Location"]
)


class LocationRequest(BaseModel):
    action: Literal["search", "reverse", "save_user_location"]
    query: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    location_label: Optional[str] = None


class LocationResponse(BaseModel):
    success: bool
    data: dict | list


class LocationService:
    SEARCH_URL = "https://photon.komoot.io/api"
    REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

    headers = {
        "User-Agent": "ConnectNow/1.0"
    }

    async def search(self, query: str):
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                self.SEARCH_URL,
                params={
                    "q": query,
                    "limit": 6
                },
                headers=self.headers
            )

        response.raise_for_status()

        data = response.json()
        locations = []

        for item in data.get("features", []):
            props = item.get("properties", {})
            coords = item.get("geometry", {}).get("coordinates", [None, None])

            lon = coords[0]
            lat = coords[1]

            city = (
                props.get("city")
                or props.get("county")
                or props.get("state")
            )

            address = ", ".join(
                filter(
                    None,
                    [
                        props.get("name"),
                        props.get("street"),
                        props.get("city"),
                        props.get("state"),
                        props.get("country")
                    ]
                )
            )

            locations.append({
                "name": props.get("name"),
                "city": city,
                "state": props.get("state"),
                "country": props.get("country"),
                "address": address,
                "latitude": lat,
                "longitude": lon
            })

        return locations

    async def reverse(self, lat: float, lng: float):
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                self.REVERSE_URL,
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "jsonv2"
                },
                headers=self.headers
            )

        response.raise_for_status()

        data = response.json()
        address = data.get("address", {})

        locality = (
            address.get("suburb")
            or address.get("neighbourhood")
            or address.get("quarter")
            or address.get("village")
            or address.get("hamlet")
        )

        city = (
            address.get("city")
            or address.get("town")
            or address.get("municipality")
            or address.get("county")
        )

        return {
            "display_name": data.get("display_name"),
            "locality": locality,
            "city": city,
            "state": address.get("state"),
            "country": address.get("country"),
            "latitude": lat,
            "longitude": lng
        }


location_service = LocationService()


@router.post("", response_model=LocationResponse)
async def location(
    request: LocationRequest,
    current_user: str = Depends(get_current_user)
):
    if request.action == "search":
        if not request.query:
            raise HTTPException(
                status_code=400,
                detail="query is required"
            )

        result = await location_service.search(request.query)

        return {
            "success": True,
            "data": result
        }

    if request.action == "reverse":
        if request.latitude is None or request.longitude is None:
            raise HTTPException(
                status_code=400,
                detail="latitude and longitude required"
            )

        result = await location_service.reverse(
            request.latitude,
            request.longitude
        )

        return {
            "success": True,
            "data": result
        }

    if request.action == "save_user_location":
        if request.latitude is None or request.longitude is None:
            raise HTTPException(
                status_code=400,
                detail="latitude and longitude required"
            )

        reverse_data = await location_service.reverse(
            request.latitude,
            request.longitude
        )

        active_city = (
            request.city
            or reverse_data.get("city")
        )

        location_label = (
            request.location_label
            or reverse_data.get("locality")
            or reverse_data.get("display_name")
        )

        ts = now_iso()

        with get_db() as conn:
            conn.execute(
                """
                UPDATE user_reg_info
                SET
                    active_city = COALESCE(?, active_city),
                    city = COALESCE(?, city),
                    latitude = ?,
                    longitude = ?,
                    location_label = ?,
                    location_source = 'gps',
                    location_updated_dt = ?
                WHERE unique_user_id = ?
                """,
                (
                    active_city,
                    active_city,
                    request.latitude,
                    request.longitude,
                    location_label,
                    ts,
                    current_user
                )
            )

        return {
            "success": True,
            "data": {
                "unique_user_id": current_user,
                "active_city": active_city,
                "location_label": location_label,
                "latitude": request.latitude,
                "longitude": request.longitude,
                "location_updated_dt": ts,
                "reverse": reverse_data
            }
        }

    raise HTTPException(
        status_code=400,
        detail="Invalid action"
    )