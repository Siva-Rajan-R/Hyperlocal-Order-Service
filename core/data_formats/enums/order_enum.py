from enum import Enum

class OrderStatusEnum(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"

class OrderOriginEnum(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    IN_STORE = "IN_STORE"
    PHONE = "PHONE"


class OrderReturnTypeEnum(str,Enum):
    EXCHANGE="EXCHANGE"
    RETURNED="RETURNED"


class OrderPaymentEnums(str,Enum):
    UPI="UPI"
    CREDIT="CREDIT"
    CASH="CASH"
    CARD="CARD"