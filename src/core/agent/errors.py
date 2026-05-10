"""Layer 2 exception taxonomy. Every failure in Layer 2 is one of these."""


class Layer2Error(Exception):
    pass


class AnthropicTransientError(Layer2Error):
    """Retry-eligible: 429, 5xx, network timeout."""
    pass


class AnthropicPermanentError(Layer2Error):
    """Do not retry: 400, 401, 403."""
    pass


class ToolValidationError(Layer2Error):
    """Claude sent malformed tool input."""
    pass


class ToolHandlerError(Layer2Error):
    """Handler raised — wrap, do not propagate to Claude."""
    pass


class StreamCancelledError(Layer2Error):
    """Barge-in cancellation, expected."""
    pass


class TriageLockViolation(Layer2Error):
    """Claude tried to deviate after hand_off — log loudly."""
    pass


class SessionStateError(Layer2Error):
    """Invalid state transition."""
    pass
