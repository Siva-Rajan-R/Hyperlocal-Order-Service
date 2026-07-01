from models.repo_models.base_repo_model import BaseRepoModel
from infras.primary_db.models.order_model import Exchanges, ExchangeItems
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from hyperlocal_platform.core.decorators.db_session_handler_dec import start_db_transaction

class ExchangeRepo:
    def __init__(self, session: AsyncSession):
        self.session=session
        self.exchange_cols = (
            Exchanges.id,
            Exchanges.ui_id,
            Exchanges.original_order_id,
            Exchanges.replacement_order_id,
            Exchanges.shop_id,
            Exchanges.customer_id,
            Exchanges.additional_amount_paid,
            Exchanges.amount_refunded,
            Exchanges.clear_outstanding_amount,
            Exchanges.reason,
            Exchanges.status,
            Exchanges.created_at,
            Exchanges.updated_at
        )

    @start_db_transaction
    async def create_exchange_with_items(self, exchange_obj: Exchanges, exchange_items: List[ExchangeItems]) -> bool:
        self.session.add(exchange_obj)
        self.session.add_all(exchange_items)
        return True
