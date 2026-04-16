from hyperlocal_platform.core.errors.messaging_errors import CommonMessagingError
from dataclasses import dataclass
from typing import Optional,Callable
from hyperlocal_platform.core.typed_dicts.saga_status_typ_dict import SagaStateErrorTypDict
from hyperlocal_platform.core.errors.messaging_errors import CommonMessagingError,EventPublishingTypDict
from hyperlocal_platform.core.enums.error_enums import ErrorTypeSEnum


class BussinessError(CommonMessagingError):
    ...

class FatalError(CommonMessagingError):
    ...

class RetryableError(CommonMessagingError):
    ...