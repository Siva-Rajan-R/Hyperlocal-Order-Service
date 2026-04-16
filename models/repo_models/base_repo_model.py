from hyperlocal_platform.core.models.service_repo_base_models import CommonBaseRepoModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional


class BaseRepoModel(CommonBaseRepoModel):
    def __init__(self,session:AsyncSession):
        self.session=session