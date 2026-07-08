from typing import Any


class ApiResponse:

    @staticmethod
    def success(data: Any):

        return {
            "code": 0,
            "msg": "success",
            "data": data
        }

    @staticmethod
    def error(msg: str, code=500):

        return {
            "code": code,
            "msg": msg,
            "data": None
        }