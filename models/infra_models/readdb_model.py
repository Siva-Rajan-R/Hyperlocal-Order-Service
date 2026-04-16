from hyperlocal_platform.core.models.readdb_models import CommonBaseReadDBModel
from typing import Optional,List,Any

class BaseReadDbModel(CommonBaseReadDBModel):
    def __init__(self,payload:Any,conditions:dict):
        self.payload=payload
        self.conditions=conditions