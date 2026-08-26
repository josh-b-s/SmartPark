from typing import List, Optional
from pydantic import BaseModel


class CarparkResult(BaseModel):
    carpark_id: str
    name: Optional[str] = None
    available_spaces: int
    confidence_score: float


class FindCarparksResponse(BaseModel):
    uuid: str
    status: str
    msg: str
    speed_inference: str
    requested_n: int
    results: List[CarparkResult]


class AnnotateCarparkResponse(BaseModel):
    carpark_id: str
    status: str
    msg: str
    image_base64: str


class TakePhotoResponse(BaseModel):
    carpark_id: str
    image_base64: str


class OpsCarpark(BaseModel):
    carpark_id: str
    name: Optional[str] = None
    available_spaces: int


class OpsCarparksResponse(BaseModel):
    status: str
    carparks: List[OpsCarpark]


class OpsActiveUsersResponse(BaseModel):
    status: str
    window_seconds: int
    active_user_count: int
