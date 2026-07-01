from models.repo_models.base_repo_model import BaseRepoModel
from infras.primary_db.models.order_model import Returns, ReturnItems
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from hyperlocal_platform.core.decorators.db_session_handler_dec import start_db_transaction

class ReturnRepo:
    def __init__(self, session: AsyncSession):
        self.session=session
        self.return_cols = (
            Returns.id,
            Returns.ui_id,
            Returns.order_id,
            Returns.shop_id,
            Returns.customer_id,
            Returns.total_refund_amount,
            Returns.total_refund_qty,
            Returns.payment_infos,
            Returns.status,
            Returns.created_at,
            Returns.updated_at
        )

    @start_db_transaction
    async def create_return_with_items(self, return_obj: Returns, return_items: List[ReturnItems]) -> bool:
        self.session.add(return_obj)
        self.session.add_all(return_items)
        return True
