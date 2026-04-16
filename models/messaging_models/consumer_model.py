from abc import ABC,abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
from hyperlocal_platform.core.models.messaging_models import CommonBaseConsumerModel


class BaseConsumerModel(CommonBaseConsumerModel):
    ...