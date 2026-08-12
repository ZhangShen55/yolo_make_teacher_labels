from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from label_review.dataset import DatasetStore
from label_review.review_ops import reject_image, save_annotation
from label_review.schemas import AnnotationUpdate, DatasetLoadRequest, RejectRequest


def parse_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.lower() in {"1", "true", "yes", "y"}


def create_app(dataset_root: str | Path) -> FastAPI:
    store_holder = {"store": DatasetStore(dataset_root)}
    app = FastAPI(title="Label Review App")
    static_dir = Path(__file__).parent / "static"

    def current_store() -> DatasetStore:
        return store_holder["store"]

    @app.get("/api/dataset/summary")
    def dataset_summary():
        return current_store().summary()

    @app.post("/api/dataset/load")
    def load_dataset(payload: DatasetLoadRequest):
        try:
            next_store = DatasetStore(payload.dataset_root)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store_holder["store"] = next_store
        return {"summary": next_store.summary(), "validation": next_store.validation_report()}

    @app.get("/api/images")
    def list_images(
        q: str | None = None,
        label: str | None = None,
        needs_review: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ):
        store = current_store()
        rows = store.filter_rows(q=q, label=label, needs_review=parse_bool(needs_review))
        return store.paginate(rows, page=page, page_size=page_size)

    @app.get("/api/images/batch")
    def batch_images(
        q: str | None = None,
        label: str | None = None,
        needs_review: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ):
        store = current_store()
        rows = store.filter_rows(q=q, label=label, needs_review=parse_bool(needs_review))
        page_data = store.paginate(rows, page=page, page_size=page_size)
        page_data["items"] = [store.get_detail(row["image_id"]) for row in page_data["items"]]
        return page_data

    @app.get("/api/images/{image_id}")
    def image_detail(image_id: str):
        store = current_store()
        try:
            return store.get_detail(image_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/images/{image_id}/file")
    def image_file(image_id: str):
        store = current_store()
        try:
            return FileResponse(store.image_path(image_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/images/{image_id}/annotation")
    def patch_annotation(image_id: str, payload: AnnotationUpdate):
        store = current_store()
        try:
            return save_annotation(
                store,
                image_id,
                [box.model_dump() for box in payload.boxes],
                needs_review=payload.needs_review,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/images/{image_id}/reject")
    def reject(image_id: str, payload: RejectRequest):
        store = current_store()
        try:
            return reject_image(store, image_id, reason=payload.reason)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="Dataset root containing images/ and labels/")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(args.dataset), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
