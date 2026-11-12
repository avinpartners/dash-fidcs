"""A route class that sends an endpoint's answer as JSON directly when it already is plain JSON (performance,
03/11/2026).

FastAPI passes every answer through jsonable_encoder, which walks it value by value before json.dumps: for the
long lists (the fund list: ~2,000 rows, ~10 MB) that walk alone took more than a quarter of a second. The endpoints
already hand over plain JSON types (common.clean converts Decimal and dates), so this route class serializes the
answer itself with the same settings as FastAPI's JSONResponse (ensure_ascii=False, allow_nan=False, compact
separators): the bytes sent are the same. An answer json.dumps cannot take (a Decimal, a date, a NaN…), a Response
the endpoint built itself, and an endpoint that sets its status or headers through FastAPI's Response parameter go
through FastAPI as before.
"""
import functools
import inspect
import json
from typing import Any, Callable

from fastapi.routing import APIRoute
from starlette.responses import Response

MEDIA_TYPE = "application/json"


def _dump(content: Any) -> bytes | None:
    """The JSON bytes FastAPI's JSONResponse would send for `content`, or None when it is not plain JSON."""
    if isinstance(content, Response):
        return None
    try:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=None,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return None


def _sets_response(endpoint: Callable) -> bool:
    """Whether the endpoint takes FastAPI's Response parameter (to set a status code, a header or a cookie)."""
    for p in inspect.signature(endpoint).parameters.values():
        if isinstance(p.annotation, type) and issubclass(p.annotation, Response):
            return True
    return False


def _wrap(endpoint: Callable, status_code: int | None) -> Callable:
    """The endpoint, answering a plain-JSON result as a ready Response (with the route's status code)."""
    if getattr(endpoint, "_fastjson", False):      # include_router builds the route again from the wrapped one
        return endpoint
    if _sets_response(endpoint):                   # it changes status or headers on FastAPI's Response: leave it
        return endpoint
    code = status_code or 200

    if inspect.iscoroutinefunction(endpoint):
        @functools.wraps(endpoint)
        async def async_endpoint(*args, **kwargs):
            result = await endpoint(*args, **kwargs)
            body = _dump(result)
            return result if body is None else Response(body, status_code=code, media_type=MEDIA_TYPE)
        async_endpoint._fastjson = True  # type: ignore[attr-defined]
        return async_endpoint

    @functools.wraps(endpoint)
    def sync_endpoint(*args, **kwargs):
        result = endpoint(*args, **kwargs)
        body = _dump(result)
        return result if body is None else Response(body, status_code=code, media_type=MEDIA_TYPE)
    sync_endpoint._fastjson = True  # type: ignore[attr-defined]
    return sync_endpoint


class FastJSONRoute(APIRoute):
    def __init__(self, path: str, endpoint: Callable, **kwargs: Any) -> None:
        # functools.wraps keeps __wrapped__, so FastAPI still reads the parameters (query, path, body) of the
        # original function.
        super().__init__(path, _wrap(endpoint, kwargs.get("status_code")), **kwargs)
