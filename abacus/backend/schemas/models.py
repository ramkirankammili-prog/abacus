from typing import Optional
from pydantic import BaseModel, Field


class DepotIn(BaseModel):
    name: str
    address: str = ""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    operating_start: str = "06:00"
    operating_end: str = "20:00"
    storage_capacity: float = Field(default=1000, gt=0)
    status: str = "Active"


class InventoryIn(BaseModel):
    name: str
    category: str = "General"
    depot_id: str
    quantity: float = Field(ge=0)
    unit: str = "units"
    expiry_date: str
    min_temp: float = 2
    max_temp: float = 8
    priority: str = "Medium"


class OrderIn(BaseModel):
    customer: str
    address: str = ""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    product_id: str
    quantity: float = Field(gt=0)
    created_at: str = ""
    window_start: str = "08:00"
    window_end: str = "17:00"
    priority: str = "Medium"
    status: str = "Pending"
    budget: Optional[float] = Field(default=None, ge=0)
    assigned_driver_id: Optional[str] = None
    assigned_vehicle_id: Optional[str] = None


class VehicleIn(BaseModel):
    name: str
    capacity: float = Field(gt=0)
    unit: str = "units"
    refrigerated: bool = True
    min_temp: float = 1
    max_temp: float = 8
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    cost_per_km: float = Field(default=18, ge=0)
    max_route_hours: float = Field(default=8, gt=0)
    status: str = "Available"


class DriverIn(BaseModel):
    name: str
    user_id: Optional[str] = None
    phone: str = ""
    license_number: str = ""
    vehicle_id: Optional[str] = None
    status: str = "Available"
