"""GET /api/bill/samples and the sample images (contracts/api.md section 11.4, #249).

The demo reads only the synthetic sample bills of a gallery (core/bills/gallery.py); a visitor's own
bill is never sent anywhere.
- `GET /api/bill/samples?lang=en|fi` lists `{samples: [{sample_id, title, language, image_url}]}` in
  gallery order. `title` follows `lang`; `language` is the bill's own language. The true fields of a
  sample (core.bills.gallery.answer_key) are never in this response.
- `GET /api/bill/samples/{file}` serves a sample's PNG. `image_url` carries the image's content hash
  as `?v=`, so with the current hash the image is cached for a year as immutable, like the app's
  hashed assets; without it (or with an old one) it is revalidated on every load. The reverse proxy
  adds the security headers of every response (deploy/Caddyfile). An unknown file is 404 `not_found`.
No database and no language model are used.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query
from fastapi.responses import FileResponse

from core.bills import gallery

from .errors import ApiError
from .schemas import Language, Model

router = APIRouter()
IMMUTABLE = "public, max-age=31536000, immutable"


class BillSample(Model):
    sample_id: str
    title: str
    language: Language
    image_url: str


class BillSamplesResponse(Model):
    samples: list[BillSample]


@router.get("/api/bill/samples", response_model=BillSamplesResponse)
def list_samples(lang: Language = Query("en")) -> BillSamplesResponse:
    return BillSamplesResponse(samples=[
        BillSample(sample_id=s.sample_id, title=s.title[lang], language=s.language,
                   image_url=f"/api/bill/samples/{s.png.name}?v={s.version}")
        for s in gallery.gallery()
    ])


@router.api_route("/api/bill/samples/{file}", methods=["GET", "HEAD"], include_in_schema=False)
def sample_image(file: str = Path(max_length=64), v: str | None = Query(None, max_length=64)) -> FileResponse:
    sample = gallery.image(file)
    if sample is None:
        raise ApiError("not_found")
    cache = IMMUTABLE if v == sample.version else "no-cache"
    return FileResponse(sample.png, media_type="image/png", headers={"Cache-Control": cache})
