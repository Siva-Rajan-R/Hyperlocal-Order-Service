from infras.read_db.main import ORDERS_COLLECTION, ORDER_STATS_COLLECTION, CUSTOMER_STATS_COLLECTION
from infras.read_db.models.order_stats_model import OrderStatsReadModel
from datetime import datetime
from icecream import ic

class OrderStatsReadDbRepo:

    @classmethod
    async def update_stats(cls, shop_id: str) -> bool:
        try:
            pipeline = [
                {"$match": {"shop_id": shop_id, "type": {"$ne": "EXCHANGE"}}},
                {
                    "$facet": {
                        "orders_stats": [
                            {
                                "$group": {
                                    "_id": None,
                                    "total_order_value": {"$sum": "$total_sellprice"},
                                    "total_orders": {"$sum": 1},
                                    "registered_customer_count": {
                                        "$sum": {"$cond": [{"$ifNull": ["$customer.customer_id", False]}, 1, 0]}
                                    },
                                    "walkin_customer_count": {
                                        "$sum": {"$cond": [{"$ifNull": ["$customer.customer_id", False]}, 0, 1]}
                                    }
                                }
                            }
                        ],
                        "items_stats": [
                            {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": True}},
                            {
                                "$group": {
                                    "_id": None,
                                    "total_returns": {
                                        "$sum": {"$cond": [{"$eq": ["$items.status", "REFUNDED"]}, 1, 0]}
                                    },
                                    "total_exchanged": {
                                        "$sum": {"$cond": [{"$eq": ["$items.status", "EXCHANGED"]}, 1, 0]}
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
            
            result = await ORDERS_COLLECTION.aggregate(pipeline).to_list(1)
            
            stats = {
                "shop_id": shop_id,
                "total_orders": 0,
                "total_order_value": 0.0,
                "total_returns": 0,
                "total_exchanged": 0,
                "registered_customer_count": 0,
                "walkin_customer_count": 0,
                "updated_at": datetime.utcnow()
            }
            
            if result and len(result) > 0:
                agg_data = result[0]
                if agg_data.get('orders_stats') and len(agg_data['orders_stats']) > 0:
                    o_stats = agg_data['orders_stats'][0]
                    stats["total_order_value"] = o_stats.get('total_order_value', 0.0)
                    stats["total_orders"] = o_stats.get('total_orders', 0)
                    stats["registered_customer_count"] = o_stats.get('registered_customer_count', 0)
                    stats["walkin_customer_count"] = o_stats.get('walkin_customer_count', 0)
                
                if agg_data.get('items_stats') and len(agg_data['items_stats']) > 0:
                    i_stats = agg_data['items_stats'][0]
                    stats["total_returns"] = i_stats.get('total_returns', 0)
                    stats["total_exchanged"] = i_stats.get('total_exchanged', 0)

            structured_data = OrderStatsReadModel(**stats).model_dump(mode="json", exclude_none=True)
            
            await ORDER_STATS_COLLECTION.replace_one(
                {"shop_id": shop_id},
                structured_data,
                upsert=True
            )
            return True
            
        except Exception as e:
            ic(f"Error updating order stats: {e}")
            return False

    @classmethod
    async def get_stats(cls, shop_id: str) -> dict:
        try:
            stats = await ORDER_STATS_COLLECTION.find_one({"shop_id": shop_id})
            if stats:
                stats.pop("_id", None)
                return stats
            return {
                "shop_id": shop_id,
                "total_orders": 0,
                "total_order_value": 0.0,
                "total_returns": 0,
                "total_exchanged": 0,
                "registered_customer_count": 0,
                "walkin_customer_count": 0
            }
        except Exception as e:
            ic(f"Error getting order stats: {e}")
            return {}

class CustomerStatsReadDbRepo:
    @classmethod
    async def update_customer_stats(cls, shop_id: str, customer_id: str):
        try:
            pipeline = [
                {"$match": {
                    "shop_id": shop_id,
                    "$or": [
                        {"customer.customer_id": customer_id},
                        {"customer_id": customer_id}
                    ],
                    "type": {"$ne": "EXCHANGE"}
                }},
                {
                    "$addFields": {
                        "total_paid_except_credit": {
                            "$reduce": {
                                "input": {"$objectToArray": {"$ifNull": ["$payments", {}]}},
                                "initialValue": 0,
                                "in": {
                                    "$add": [
                                        "$$value",
                                        {"$cond": [{"$eq": ["$$this.k", "CREDIT"]}, 0, "$$this.v"]}
                                    ]
                                }
                            }
                        }
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_sales_count": {"$sum": 1},
                        "total_sales_value": {"$sum": "$total_sellprice"},
                        "outstanding_amount": {
                            "$sum": {"$subtract": ["$total_sellprice", "$total_paid_except_credit"]}
                        }
                    }
                }
            ]
            
            cursor = ORDERS_COLLECTION.aggregate(pipeline)
            result = await cursor.to_list(length=1)
            
            stats_data = {
                "shop_id": shop_id,
                "customer_id": customer_id,
                "total_sales_count": 0,
                "total_sales_value": 0.0,
                "outstanding_amount": 0.0
            }
            
            if result and len(result) > 0:
                agg = result[0]
                stats_data["total_sales_count"] = agg.get("total_sales_count", 0)
                stats_data["total_sales_value"] = agg.get("total_sales_value", 0.0)
                stats_data["outstanding_amount"] = max(0, agg.get("outstanding_amount", 0.0))
                
            await CUSTOMER_STATS_COLLECTION.replace_one(
                {"shop_id": shop_id, "customer_id": customer_id},
                stats_data,
                upsert=True
            )
            return stats_data
        except Exception as e:
            ic(f"Error updating customer stats: {e}")
            return None
            
    @classmethod
    async def get_customer_stats(cls, shop_id: str, customer_id: str):
        stats = await CUSTOMER_STATS_COLLECTION.find_one({"shop_id": shop_id, "customer_id": customer_id})
        if not stats:
            stats = await cls.update_customer_stats(shop_id, customer_id)
        
        if stats:
            stats.pop("_id", None)
            return stats
            
        return {
            "total_sales_count": 0,
            "total_sales_value": 0.0,
            "outstanding_amount": 0.0
        }


class DashboardStatsRepo:
    """Aggregates dashboard analytics from the orders collection, filtered by date range."""

    @classmethod
    async def get_dashboard_stats(cls, shop_id: str, start_date: datetime, end_date: datetime, supplier_id: str = None, category: str = None) -> dict:
        try:
            date_match = {
                "shop_id": shop_id,
                "created_at": {"$gte": start_date.isoformat(), "$lte": end_date.isoformat()}
            }
            
            item_elem_match = {}
            item_match = {}
            if supplier_id:
                item_elem_match["datas.supplier"] = supplier_id
                item_match["items.datas.supplier"] = supplier_id
            if category:
                item_elem_match["datas.category"] = category
                item_match["items.datas.category"] = category
                
            if item_elem_match:
                date_match["items"] = {"$elemMatch": item_elem_match}

            pipeline = [
                {"$match": date_match},
                {
                    "$facet": {
                        # ── Overall stats (excl. EXCHANGE for revenue) ──
                        "overall": [
                            {"$match": {"type": {"$ne": "EXCHANGE"}}},
                            {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": False}},
                            {"$match": item_match},
                            {
                                "$group": {
                                    "_id": "$_id",
                                    "order_revenue": {"$sum": {"$multiply": ["$items.sell_price", "$items.quantity"]}},
                                    "order_cost": {"$sum": {"$multiply": ["$items.buy_price", "$items.quantity"]}},
                                }
                            },
                            {
                                "$group": {
                                    "_id": None,
                                    "total_orders": {"$sum": 1},
                                    "gross_revenue": {"$sum": "$order_revenue"},
                                    "total_cost": {"$sum": "$order_cost"},
                                }
                            },
                            {
                                "$addFields": {
                                    "total_profit": {"$subtract": ["$gross_revenue", "$total_cost"]},
                                    "avg_order_value": {
                                        "$cond": [
                                            {"$gt": ["$total_orders", 0]},
                                            {"$divide": ["$gross_revenue", "$total_orders"]},
                                            0
                                        ]
                                    }
                                }
                            }
                        ],
                        # ── Exchange count (from item-level EXCHANGED status) ──
                        "exchanges": [
                            {"$match": {"type": {"$ne": "EXCHANGE"}}},
                            {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": False}},
                            {"$match": {"items.status": "EXCHANGED"}},
                            {
                                "$group": {
                                    "_id": None,
                                    "total_exchanges_count": {"$sum": 1}
                                }
                            }
                        ],
                        # ── Returns value (from item-level REFUNDED status) ──
                        "returns": [
                            {"$match": {"type": {"$ne": "EXCHANGE"}}},
                            {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": False}},
                            {"$match": {"items.status": "REFUNDED", **item_match}},
                            {
                                "$group": {
                                    "_id": None,
                                    "total_returns_value": {
                                        "$sum": {"$multiply": ["$items.sell_price", "$items.quantity"]}
                                    },
                                    "total_returns_count": {"$sum": 1}
                                }
                            }
                        ],
                        # ── Payment breakdown ──
                        "payments": [
                            {"$match": {"type": {"$ne": "EXCHANGE"}}},
                            {
                                "$addFields": {
                                    "payment_entries": {"$objectToArray": {"$ifNull": ["$payments", {}]}}
                                }
                            },
                            {"$unwind": {"path": "$payment_entries", "preserveNullAndEmptyArrays": False}},
                            {
                                "$group": {
                                    "_id": "$payment_entries.k",
                                    "total": {"$sum": "$payment_entries.v"},
                                    "count": {"$sum": 1}
                                }
                            },
                            {"$sort": {"total": -1}}
                        ],
                        # ── Top 5 products by quantity ──
                        "top_products": [
                            {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": False}},
                            {"$match": {"items.status": {"$nin": ["REFUNDED", "EXCHANGED"]}, **item_match}},
                            {
                                "$group": {
                                    "_id": "$items.inventory_id",
                                    "name": {"$first": {"$ifNull": [
                                        "$items.name",
                                        {"$ifNull": ["$items.datas.product_name", "Unknown"]}
                                    ]}},
                                    "total_qty": {"$sum": "$items.quantity"},
                                    "total_revenue": {
                                        "$sum": {"$multiply": ["$items.sell_price", "$items.quantity"]}
                                    },
                                    "total_cost": {
                                        "$sum": {"$multiply": ["$items.buy_price", "$items.quantity"]}
                                    }
                                }
                            },
                            {
                                "$addFields": {
                                    "total_profit": {"$subtract": ["$total_revenue", "$total_cost"]}
                                }
                            },
                            {"$sort": {"total_qty": -1}},
                            {"$limit": 5}
                        ],
                        # ── Daily trend (revenue + profit by day) ──
                        "daily_trend": [
                            {"$match": {"type": {"$ne": "EXCHANGE"}}},
                            {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": False}},
                            {"$match": item_match},
                            {
                                "$addFields": {
                                    "order_date": {"$substr": ["$created_at", 0, 10]}
                                }
                            },
                            {
                                "$group": {
                                    "_id": {
                                        "order_id": "$_id",
                                        "date": "$order_date"
                                    },
                                    "order_revenue": {"$sum": {"$multiply": ["$items.sell_price", "$items.quantity"]}},
                                    "order_cost": {"$sum": {"$multiply": ["$items.buy_price", "$items.quantity"]}}
                                }
                            },
                            {
                                "$group": {
                                    "_id": "$_id.date",
                                    "revenue": {"$sum": "$order_revenue"},
                                    "cost": {"$sum": "$order_cost"},
                                    "orders": {"$sum": 1}
                                }
                            },
                            {
                                "$addFields": {
                                    "profit": {"$subtract": ["$revenue", "$cost"]}
                                }
                            },
                            {"$sort": {"_id": 1}}
                        ],
                        # ── Sales by Category ──
                        "sales_by_category": [
                            {"$match": {"type": {"$ne": "EXCHANGE"}}},
                            {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": False}},
                            {"$match": {"items.status": {"$nin": ["REFUNDED", "EXCHANGED"]}, **item_match}},
                            {
                                "$group": {
                                    "_id": {"$ifNull": ["$items.datas.category", "Uncategorized"]},
                                    "total_revenue": {"$sum": {"$multiply": ["$items.sell_price", "$items.quantity"]}}
                                }
                            },
                            {"$sort": {"total_revenue": -1}}
                        ],
                        # ── Top Suppliers ──
                        "top_suppliers": [
                            {"$match": {"type": {"$ne": "EXCHANGE"}}},
                            {"$unwind": {"path": "$items", "preserveNullAndEmptyArrays": False}},
                            {"$match": {"items.status": {"$nin": ["REFUNDED", "EXCHANGED"]}, **item_match}},
                            {
                                "$group": {
                                    "_id": {"$ifNull": ["$items.datas.supplier", "Unknown"]},
                                    "total_revenue": {"$sum": {"$multiply": ["$items.sell_price", "$items.quantity"]}},
                                    "total_cost": {"$sum": {"$multiply": ["$items.buy_price", "$items.quantity"]}},
                                    "total_qty": {"$sum": "$items.quantity"}
                                }
                            },
                            {
                                "$addFields": {
                                    "total_profit": {"$subtract": ["$total_revenue", "$total_cost"]}
                                }
                            },
                            {"$sort": {"total_revenue": -1}},
                            {"$limit": 5}
                        ]
                    }
                }
            ]

            result = await ORDERS_COLLECTION.aggregate(pipeline).to_list(1)

            # Build response
            stats = {
                "shop_id": shop_id,
                "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
                "total_orders": 0,
                "gross_revenue": 0.0,
                "total_cost": 0.0,
                "total_profit": 0.0,
                "net_revenue": 0.0,
                "avg_order_value": 0.0,
                "total_returns_value": 0.0,
                "total_returns_count": 0,
                "total_exchanges_count": 0,
                "gross_margin_pct": 0.0,
                "payment_breakdown": [],
                "top_products": [],
                "daily_trend": [],
                "sales_by_category": [],
                "top_suppliers": []
            }

            if result and len(result) > 0:
                data = result[0]

                # Overall
                if data.get("overall") and len(data["overall"]) > 0:
                    o = data["overall"][0]
                    stats["total_orders"] = o.get("total_orders", 0)
                    stats["gross_revenue"] = round(o.get("gross_revenue", 0.0), 2)
                    stats["total_cost"] = round(o.get("total_cost", 0.0), 2)
                    stats["total_profit"] = round(o.get("total_profit", 0.0), 2)
                    stats["avg_order_value"] = round(o.get("avg_order_value", 0.0), 2)

                # Exchanges
                if data.get("exchanges") and len(data["exchanges"]) > 0:
                    stats["total_exchanges_count"] = data["exchanges"][0].get("total_exchanges_count", 0)

                # Returns
                if data.get("returns") and len(data["returns"]) > 0:
                    r = data["returns"][0]
                    stats["total_returns_value"] = round(r.get("total_returns_value", 0.0), 2)
                    stats["total_returns_count"] = r.get("total_returns_count", 0)

                stats["net_revenue"] = round(stats["gross_revenue"] - stats["total_returns_value"], 2)

                # Gross margin
                if stats["gross_revenue"] > 0:
                    stats["gross_margin_pct"] = round(
                        (stats["total_profit"] / stats["gross_revenue"]) * 100, 1
                    )

                # Payment breakdown
                stats["payment_breakdown"] = [
                    {"method": p["_id"], "total": round(p["total"], 2), "count": p["count"]}
                    for p in data.get("payments", [])
                ]

                # Top products
                stats["top_products"] = [
                    {
                        "inventory_id": p["_id"],
                        "name": p.get("name", "Unknown"),
                        "total_qty": p.get("total_qty", 0),
                        "total_revenue": round(p.get("total_revenue", 0.0), 2),
                        "total_profit": round(p.get("total_profit", 0.0), 2)
                    }
                    for p in data.get("top_products", [])
                ]

                # Daily trend
                stats["daily_trend"] = [
                    {
                        "date": d["_id"],
                        "revenue": round(d.get("revenue", 0.0), 2),
                        "profit": round(d.get("profit", 0.0), 2),
                        "orders": d.get("orders", 0)
                    }
                    for d in data.get("daily_trend", [])
                ]

                # Sales by Category
                stats["sales_by_category"] = [
                    {
                        "category": c["_id"],
                        "revenue": round(c.get("total_revenue", 0.0), 2)
                    }
                    for c in data.get("sales_by_category", [])
                ]

                # Top Suppliers
                stats["top_suppliers"] = [
                    {
                        "supplier_id": s["_id"],
                        "total_qty": s.get("total_qty", 0),
                        "total_revenue": round(s.get("total_revenue", 0.0), 2),
                        "total_profit": round(s.get("total_profit", 0.0), 2)
                    }
                    for s in data.get("top_suppliers", [])
                ]

            return stats

        except Exception as e:
            ic(f"Error getting dashboard stats: {e}")
            return {"error": str(e)}

