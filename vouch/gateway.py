"""The ONLY code that changes vendor bank details or releases payment. Refuses unless the item is APPROVED.
(DB triggers back this up: bank columns and payments rows cannot change without the matching audit rows.)"""
from . import core
from .rails import PaymentOrder, SqliteRail

REQUESTERS = {"accountant", "gateway"}   # roles allowed to ask the gateway to post


def post_item(conn, item_id, requested_by, reason="", requested_by_id=None, rail=None):
    rail = rail or SqliteRail()
    ev = {"requested_by": requested_by, "requested_by_id": requested_by_id}
    if requested_by not in REQUESTERS:
        item = core.load_item(conn, item_id)
        aid = core.record_denied(conn, actor=requested_by, action="post", item_id=item_id, reason=reason, code="POST_REQUESTER_NOT_ALLOWED",
                                 detail=f"{requested_by} cannot request a post", actor_id=requested_by_id, evidence=ev,
                                 state=item["state"] if item else None, vendor_id=item["vendor_id"] if item else None)
        raise core.Denied(core.Decision(False, "POST_REQUESTER_NOT_ALLOWED", f"{requested_by} cannot request a post"), aid)

    def release(conn, item):               # runs inside the post transaction, after the state change + 'post' audit row
        if item["state"] != "APPROVED":    # defence in depth; can() already guarantees this
            raise RuntimeError("gateway refuses: item not APPROVED")
        vendor = item["vendor"]
        bank = dict(vendor["bank"])
        if core.is_bank_change(item):
            new = item["claim"]["claimed_bank"]
            after = {"bank_name": new.get("bank_name"), "routing": new["routing"], "account": new["account"]}
            core.append_audit(conn, actor="gateway", action="bank_change", outcome="applied", item_id=item["id"], vendor_id=vendor["vendor_id"],
                              reason=f"bank details updated per approved item {item['id']} (approved by {item['approved_by']})",
                              evidence={"item_id": item["id"], "approved_by": item["approved_by"]}, before=bank, after=after)
            conn.execute("UPDATE vendors SET bank_name=?, bank_routing=?, bank_account=? WHERE vendor_id=?",
                         (after["bank_name"], after["routing"], after["account"], vendor["vendor_id"]))
            bank = after
        receipt = rail.release(conn, PaymentOrder(item["id"], vendor["vendor_id"], item["claim"]["amount"],
                                                  str(bank["routing"]), str(bank["account"]), idempotency_key=item["id"]))
        core.append_audit(conn, actor="gateway", action="payment_release", outcome="applied", item_id=item["id"],
                          vendor_id=vendor["vendor_id"], reason="payment released", evidence=receipt,
                          after={"amount": item["claim"]["amount"], "to_account_last4": str(bank["account"])[-4:]})

    return core.transition(conn, item_id, "gateway", "post", reason or f"post requested by {requested_by}", ev,
                           actor_id=requested_by_id, effects=release, _gateway_key=core._GATEWAY_KEY)
