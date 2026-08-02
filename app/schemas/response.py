from typing import Any, Optional

from app.utils.request_context import get_request_id


class ApiResponse:

    @staticmethod
    def success(data: Any, request_id: Optional[str] = None):

        return {
            "code": 0,
            "msg": "success",
            "request_id": request_id or get_request_id(),
            "data": data
        }

    @staticmethod
    def error(msg: str, code=500, request_id: Optional[str] = None):

        return {
            "code": code,
            "msg": msg,
            "request_id": request_id or get_request_id(),
            "data": None
        }
