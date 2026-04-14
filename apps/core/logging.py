import contextvars
import logging
import uuid

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str:
    cid = _correlation_id.get()
    if not cid:
        cid = str(uuid.uuid4())
        _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str | None) -> contextvars.Token:
    return _correlation_id.set(cid or str(uuid.uuid4()))


def reset_correlation_id(token: contextvars.Token) -> None:
    _correlation_id.reset(token)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = get_correlation_id()
        return True
