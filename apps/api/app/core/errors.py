class AppError(Exception):
    """An API error rendered as {"code", "detail"}; never put secrets in detail."""

    def __init__(
        self, status: int, code: str, detail: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(code, detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = headers
