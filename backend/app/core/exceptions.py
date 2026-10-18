class AppError(Exception):
    """Error bisnis -> {"detail": "...", **extra} dengan status_code terkait.

    `extra` memuat data terstruktur (mis. 409 stok kurang -> {"shortages": [...]}).
    """

    def __init__(self, status_code: int, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.status_code, self.detail, self.extra = status_code, detail, extra or {}
