"""Payment rail interface. gateway.py is the only caller. Swap SqliteRail for a Capital One Nessie / Coinbase-testnet rail
by implementing release(); keep idempotency_key (= item id) so a retry after a crash can never pay twice."""
from dataclasses import dataclass
from typing import Protocol

from .core import now


@dataclass(frozen=True)
class PaymentOrder:
    item_id: str
    vendor_id: str
    amount: float
    bank_routing: str
    bank_account: str
    idempotency_key: str


class PaymentRail(Protocol):
    name: str

    def release(self, conn, order: PaymentOrder) -> dict:
        """Release the payment and return a receipt dict. Called inside the gateway's DB transaction; raising aborts the
        whole post (state change and audit row roll back). An external rail must use order.idempotency_key."""


class SqliteRail:
    name = "sqlite"

    def release(self, conn, order):
        cur = conn.execute(
            "INSERT INTO payments(item_id,vendor_id,amount,bank_routing,bank_account,rail,idempotency_key,released_at) VALUES(?,?,?,?,?,?,?,?)",
            (order.item_id, order.vendor_id, order.amount, order.bank_routing, order.bank_account, self.name, order.idempotency_key, now()))
        return {"rail": self.name, "payment_id": cur.lastrowid, "idempotency_key": order.idempotency_key}
