from __future__ import annotations

from pydantic import BaseModel


class BoxUpdate(BaseModel):
    box_id: str = "0"
    box_xyxy: list[float]
    labels: list[str]


class AnnotationUpdate(BaseModel):
    boxes: list[BoxUpdate]
    needs_review: bool = False


class RejectRequest(BaseModel):
    reason: str = ""


class DatasetLoadRequest(BaseModel):
    dataset_root: str
