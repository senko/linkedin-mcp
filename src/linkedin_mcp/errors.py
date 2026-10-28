"""Exception hierarchy for the LinkedIn Member Data Portability client."""

TOKEN_GENERATOR_URL = "https://www.linkedin.com/developers/tools/oauth/token-generator"


class LinkedInError(Exception):
    """Base class for all errors raised by this package."""


class ConfigurationError(LinkedInError):
    """Raised when required configuration (such as the access token) is missing or invalid."""


class LinkedInConnectionError(LinkedInError):
    """Raised when the LinkedIn API cannot be reached after all retries."""


class LinkedInAPIError(LinkedInError):
    """Raised when the LinkedIn API returns an error response.

    Attributes:
        status: HTTP status code of the response.
        message: Error description from the response body (or the raw body text).
        service_error_code: LinkedIn-specific error subcode, if present.
        code: LinkedIn error code string, if present.
    """

    def __init__(
        self,
        status: int,
        message: str,
        *,
        service_error_code: int | None = None,
        code: str | None = None,
    ) -> None:
        """Create an API error.

        Args:
            status: HTTP status code of the response.
            message: Error description from the response body.
            service_error_code: LinkedIn-specific error subcode, if present.
            code: LinkedIn error code string, if present.
        """
        self.status = status
        self.message = message
        self.service_error_code = service_error_code
        self.code = code
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return a human-readable description of the error."""
        return f"LinkedIn API error {self.status}: {self.message}"


class BadRequestError(LinkedInAPIError):
    """HTTP 400: the request was malformed (for example, an unsupported snapshot domain)."""


class AuthenticationError(LinkedInAPIError):
    """HTTP 401: the access token is missing, invalid, expired or revoked."""

    def __str__(self) -> str:
        """Return the error description with instructions to regenerate the token."""
        return (
            f"{super().__str__()}. The access token is invalid or expired (tokens last 60 days). "
            f"Generate a new one at {TOKEN_GENERATOR_URL} and update LINKEDIN_ACCESS_TOKEN."
        )


class PermissionDeniedError(LinkedInAPIError):
    """HTTP 403: the token does not have the permission required for this call."""


class NotFoundError(LinkedInAPIError):
    """HTTP 404: the requested resource does not exist."""


class RateLimitError(LinkedInAPIError):
    """HTTP 429: the daily application or member rate limit has been reached."""


class ServerError(LinkedInAPIError):
    """HTTP 5xx: LinkedIn failed to process the request."""


_ERRORS_BY_STATUS: dict[int, type[LinkedInAPIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    429: RateLimitError,
}


def api_error_for_status(
    status: int,
    message: str,
    *,
    service_error_code: int | None = None,
    code: str | None = None,
) -> LinkedInAPIError:
    """Build the most specific API error for an HTTP status code.

    Args:
        status: HTTP status code of the response.
        message: Error description from the response body.
        service_error_code: LinkedIn-specific error subcode, if present.
        code: LinkedIn error code string, if present.

    Returns:
        An instance of the matching `LinkedInAPIError` subclass.
    """
    if status >= 500:
        error_class: type[LinkedInAPIError] = ServerError
    else:
        error_class = _ERRORS_BY_STATUS.get(status, LinkedInAPIError)
    return error_class(status, message, service_error_code=service_error_code, code=code)
