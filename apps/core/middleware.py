import uuid

from apps.core.logging import set_correlation_id, reset_correlation_id


class RequestCorrelationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header_cid = request.headers.get("X-Correlation-ID") or request.headers.get(
            "X-Request-ID"
        )
        cid = header_cid or str(uuid.uuid4())
        token = set_correlation_id(cid)
        request.correlation_id = cid
        try:
            response = self.get_response(request)
        finally:
            reset_correlation_id(token)
        response["X-Correlation-ID"] = cid
        return response
