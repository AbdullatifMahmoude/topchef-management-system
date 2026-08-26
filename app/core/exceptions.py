from fastapi import HTTPException, status


class AppExceptions(HTTPException):

    def __init__(
            self,
            status_code: int,
            detail: str,
            error_code: str | None = None):

        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class AuthenticationError(AppExceptions):
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="AUTH_ERROR"
        )


class AuthorizationError(AppExceptions):
    def __init__(self, detail: str = "Not authorized"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="FORBIDDEN"
        )


class ValidationError(AppExceptions):
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="VALIDATION_ERROR"
        )


class IdempotencyError(AppExceptions):
    def __init__(self, detail: str = "Duplicate request"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            error_code="DUPLICATE_REQUEST"
        )


class NotFoundError(AppExceptions):
    def __init__(self, resource: str = "Resource"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} not found",
            error_code="NOT_FOUND"
        )


class AuthenticationServiceUnavailable(AppExceptions):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
            error_code="AUTH_SERVICE_UNAVAILABLE",
        )
