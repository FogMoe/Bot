"""Domain-specific exceptions."""


class ServiceError(Exception):
    pass


class CardNotFound(ServiceError):
    pass


class SubscriptionError(ServiceError):
    pass


class RateLimitExceeded(ServiceError):
    pass
