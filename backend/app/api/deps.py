import json
from collections.abc import Iterator

from fastapi import Request
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.core.i18n import translate_view
from app.database import SessionLocal


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def request_lang(request: Request) -> str:
    """"en" when the browser asks for English (Accept-Language: en), else "id"."""
    return "en" if request.headers.get("accept-language", "").lower().startswith("en") else "id"


class TranslatedRoute(APIRoute):
    """JSON responses whose display texts (titles, summaries, labels...) are stored/composed in Indonesian are
    translated for English users (`translate_view`); used by the Hub and activity routers."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def translated(request: Request):
            response = await handler(request)
            if request_lang(request) != "en" or response.media_type != "application/json" or not response.body:
                return response
            body = json.dumps(translate_view(json.loads(response.body), "en"), ensure_ascii=False,
                              separators=(",", ":")).encode()
            response.body = body
            response.headers["content-length"] = str(len(body))
            return response

        return translated
