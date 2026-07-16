from typing import Optional


def error_response(error: str, code: str, details: Optional[dict] = None) -> dict:
    response = {"error": error, "code": code}
    if details:
        response["details"] = details
    return response
