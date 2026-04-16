"""Policy violations for plans, quotas, and suspension (API + send pipeline)."""


class PolicyError(Exception):
    """Raised when an account/tenant action is blocked by policy."""

    def __init__(self, code: str, detail: str, *, status_code: int = 403) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)
