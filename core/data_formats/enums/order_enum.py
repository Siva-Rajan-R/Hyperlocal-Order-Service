from enum import Enum

class OrderStatusEnum(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"
    CONFIRMED = "CONFIRMED"
    REFUNDED = "REFUNDED"
    EXCHANGED = "EXCHANGED"
    RETURNED = "RETURNED"

class OrderOriginEnum(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    IN_STORE = "IN_STORE"
    PHONE = "PHONE"
    POS = "POS"


class OrderReturnTypeEnum(str, Enum):
    EXCHANGE = "EXCHANGE"
    RETURNED = "RETURNED"


class OrderPaymentEnums(str, Enum):
    UPI = "UPI"
    CREDIT = "CREDIT"
    CASH = "CASH"
    CARD = "CARD"
    ON_CREDIT = "ON_CREDIT"
    SPLIT = "SPLIT"
    OTHER = "OTHER"