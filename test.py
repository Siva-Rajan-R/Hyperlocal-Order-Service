order_id = generate_uuid()

        order_items_toadd = []
        for item in cart_items:
            item_id = generate_uuid()
            item_toadd = OrderItemsDbSchema(
                id=item_id,
                order_id=order_id,
                product_id=item['product_id'],
                variant_id=item.get('variant_id'),
                batch_id=item.get('batch_id'),
                serialno_id=item.get('serialno_id'),
                serial_numbers=item.get('serial_numbers'),
                buy_price=item.get('buy_price', 0.0),
                sell_price=item.get('sell_price', 0.0),
                quantity=item.get('quantity', item.get('qty', 0.0)),
                status=data.status.value if hasattr(data.status, 'value') else data.status,
                gst=item.get('gst')
            )
            order_items_toadd.append(OrderItems(**item_toadd.model_dump()))

        customer_id = data.customer_id
        if data.customer:
            customer_id = data.customer.customer_id or customer_id

        # UI_ID sequence generation
        from infras.read_db.repos.shopidconfig_repo import ShopIdConfigReadDbRepo
        from core.utils.id_formatter import format_ui_id

        shop_config = await ShopIdConfigReadDbRepo.get_config(data.shop_id)
        order_config = shop_config.get("order", {})
        prefix = order_config.get("prefix", "ORD")
        start_from = order_config.get("start_from", 1)

        raw_sequence = await OrdersRepo(session=self.session).get_next_sequence(data.shop_id, start_from)
        ui_id_str = format_ui_id(prefix, start_from, raw_sequence)

        # Merge customer data into additional_infos if customer exists
        final_additional_infos = data.additional_infos or {}
        if data.customer:
            final_additional_infos["customer"] = data.customer.model_dump()
        
        order_toadd = CreateOrderDbSchema(
            id=order_id,
            ui_id=ui_id_str,
            shop_id=data.shop_id,
            customer_id=customer_id,
            status=data.status.value if hasattr(data.status, 'value') else data.status,
            origin=data.origin.value if hasattr(data.origin, 'value') else data.origin,
            type=data.type or 'NORMAL',
            calculation_infos=data.calculation_infos,
            charges_infos=data.charges_infos,
            item_infos=getattr(data, 'item_infos', {}),
            payment_infos=data.payment_infos,
            date=datetime.now(timezone.utc),
            additional_infos=final_additional_infos
        )
        
        order_res = await OrdersRepo(session=self.session).create(data=order_toadd)
        if order_res:
            item_res = await OrdersRepo(session=self.session).create_bulk_items(datas=order_items_toadd)
            if not item_res:
                order_res = None
        
        if order_res:
            await self.session.commit()
            order_data = await OrdersRepo(session=self.session).getby_id(data=GetOrderByIdSchema(id=order_id, shop_id=data.shop_id))
            if order_data:
                await OrderReadDbRepo.replace_order(data=dict(order_data))

            # Activity log
            from hyperlocal_platform.core.utils.activity_logger import ActivityLogger
            item_count = len(cart_items)
            
            try:
                from messaging.main import RabbitMQMessagingConfig
                rabbitmq_msg_obj = RabbitMQMessagingConfig()
                await rabbitmq_msg_obj.publish_event(
                    routing_key="activity_logs.routing.key",
                    exchange_name="activity_logs.exchange",
                    payload={
                        "shop_id": data.shop_id,
                        "user_name": "siva",
                        "service": "Billing",
                        "action": "CREATE",
                        "entity_type": "Order",
                        "entity_id": order_id,
                        "description": f"Created new order with {item_count} item(s)",
                        "changes": [
                            {"field": "items", "before": "", "after": str(item_count)},
                            {"field": "type", "before": "", "after": str(data.type)}
                        ]
                    },
                    headers={}
                )
            except Exception as e:
                ic(f"Failed to publish activity log: {e}")

            # Inject missing fields for response schema validation
            order_res_dict = dict(order_res)
            order_res_dict['total_quantity'] = data.calculation_infos.get('total_quantity', 0.0)
            order_res_dict['total_buyprice'] = data.calculation_infos.get('total_buyprice', 0.0)
            order_res_dict['total_sellprice'] = data.calculation_infos.get('total_sellprice', 0.0)
            
            payments = {}
            for p in data.payment_infos:
                mode = p.get('mode')
                amount = p.get('amount', 0.0)
                if mode:
                    payments[mode] = payments.get(mode, 0.0) + amount
            order_res_dict['payments'] = payments
            order_res = order_res_dict

        return order_res