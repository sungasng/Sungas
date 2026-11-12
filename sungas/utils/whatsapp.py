"""Patch 0032 -- WhatsApp approval alerts via the LMD companion (Twilio).

Phone = active Employee.cell_number of the user. Needs site config
`lmd_backend_url` + `lmd_hook_secret`; without them nothing is sent (bell/email still go).
"""
from __future__ import annotations

import re

import frappe

WA_DOCTYPES = {"LPG Price Change Request", "LPG Bulk Price Upload", "Transit Loss Variance Case",
               "Inter-Outlet Variance Case", "Purchase Order", "Customer Group Change Request"}
HOOK_PATH = "/api/lmd/erp/hooks/approval-alert"


def normalize_phone(raw) -> str | None:
    s = re.sub(r"[^\d+]", "", str(raw or ""))
    if s.startswith("+"):
        return s if len(s) >= 11 else None
    if s.startswith("234") and len(s) == 13:
        return "+" + s
    if s.startswith("0") and len(s) == 11:
        return "+234" + s[1:]
    return None


def phone_for(user: str) -> str | None:
    return normalize_phone(frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "cell_number"))


def _conf():
    return frappe.conf.get("lmd_backend_url"), frappe.conf.get("lmd_hook_secret")


def send(users, template: str, variables: dict, ref: str = "") -> int:
    """Queue one WhatsApp per user that has a mobile number. Never raises."""
    url, secret = _conf()
    if not url or not secret:
        return 0
    queued = 0
    try:
        for user in users or []:
            phone = phone_for(user)
            if not phone:
                continue
            frappe.enqueue("sungas.utils.whatsapp.post", queue="short", enqueue_after_commit=True,
                           phone=phone, template=template, variables={k: str(v) for k, v in variables.items()},
                           ref=f"{ref}:{user}")
            queued += 1
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.whatsapp.send")
    return queued


def post(phone, template, variables, ref=""):
    from frappe.integrations.utils import make_post_request

    url, secret = _conf()
    try:
        make_post_request(url.rstrip("/") + HOOK_PATH, headers={"X-LMD-Hook-Secret": secret},
                          json={"to_phone": phone, "template": template, "variables": variables, "ref": ref})
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sungas.whatsapp.post")


def doc_url(doctype, name) -> str:
    return frappe.utils.get_url(f"/app/{frappe.scrub(doctype).replace('_', '-')}/{name}")


def first_name(user) -> str:
    return frappe.db.get_value("User", user, "first_name") or "there"


def workflow_alert(doctype, name, users, state, actions, actor):
    if doctype not in WA_DOCTYPES:
        return
    from sungas.approval_link import link_for

    for user in users:
        if not phone_for(user):
            continue
        link = link_for(user, doctype, name, state, actions) or doc_url(doctype, name)
        send([user], "sungas_approval_needed", {
            "approver_name": first_name(user), "doc_label": f"{doctype} {name}",
            "summary": f"Raised/moved by {frappe.db.get_value('User', actor, 'full_name') or actor}",
            "state": f"{state} ({' / '.join(actions)})", "link": link},
            ref=f"{doctype}:{name}:{state}")


def workflow_update(doctype, name, owner, state):
    if doctype in WA_DOCTYPES:
        send([owner], "sungas_approval_update", {
            "requester_name": first_name(owner), "doc_label": f"{doctype} {name}", "state": state,
            "note": "-", "link": doc_url(doctype, name)}, ref=f"{doctype}:{name}:{state}")


@frappe.whitelist()
def health() -> dict:
    """System Manager check: is WhatsApp wired, and who is missing a mobile number."""
    frappe.only_for("System Manager")
    from sungas.commercial_desk import desk_users, _users_with, HOS_ROLES

    watch = set(desk_users()) | set(_users_with(list(HOS_ROLES) + ["LPG Head of Finance", "LPG Head of Operations", "COO"]))
    url, secret = _conf()
    return {"configured": bool(url and secret), "lmd_backend_url": url,
            "missing_mobile": sorted(u for u in watch if not phone_for(u))}
