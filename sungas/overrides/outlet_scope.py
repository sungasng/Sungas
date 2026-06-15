"""sungas.overrides.outlet_scope
================================

SQL-level outlet scoping for cashier-facing POS doctypes. Layered on top of
the User Permission system so even malicious API calls can't pull other
outlets' shifts.

A user is "scoped" if they hold NONE of the cross-outlet exempt roles
defined in EXEMPT_ROLES. For scoped users we constrain queries by their
allowed POS Profile names (read from User Permission table).

This is invoked by Frappe via the `permission_query_conditions` and
`has_permission` hooks declared in `sungas/hooks.py`.
"""

from __future__ import annotations

import frappe  # type: ignore  # provided by Frappe at runtime

EXEMPT_ROLES = frozenset({
    "System Manager",
    "Accounts Manager",
    "LPG Head of Operations",
    "LPG Head of Sales",
    "LPG Head of Finance",
    "HR Manager",
    "POS Manager",
    "Sales Manager",
    "Auditor",
})


def _is_exempt(user: str) -> bool:
    if user in ("Administrator", "Guest"):
        return user == "Administrator"
    roles = set(frappe.get_roles(user) or [])
    return bool(roles & EXEMPT_ROLES)


def _allowed_profiles(user: str) -> list[str]:
    """Return list of POS Profile names this user is allowed.

    Resolution order:
      1. Explicit User Permission rows (allow=POS Profile).
      2. Implicit assignment via the POS Profile User child table.

    Implicit assignment is a safety net only -- explicit User Permission
    rows still take precedence and are the recommended scoping mechanism.

    Result is cached per request on frappe.local to avoid repeated lookups
    when permission_query_conditions fires across multiple list queries in
    the same session (e.g. paginating POS Closing Shift list view).
    """
    cache_key = f"sungas_allowed_profiles::{user}"
    cached = getattr(frappe.local, cache_key, None)
    if cached is not None:
        return cached

    rows = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "POS Profile"},
        fields=["for_value"],
    )
    profiles = [r.for_value for r in rows if r.get("for_value")]
    if not profiles:
        child_rows = frappe.get_all(
            "POS Profile User",
            filters={"user": user},
            fields=["parent"],
        )
        profiles = [r.parent for r in child_rows if r.get("parent")]

    setattr(frappe.local, cache_key, profiles)
    return profiles


def _sql_in_clause(values: list[str]) -> str:
    """Safely build a SQL IN(...) clause from a list of strings."""
    escaped = [frappe.db.escape(v) for v in values]
    return "(" + ", ".join(escaped) + ")"


def _query_by_profile_field(user: str, table: str, field: str) -> str:
    """Return a SQL WHERE-fragment restricting `table.field` to user's profiles.

    Returns an empty string for exempt users (no restriction).
    Returns `1=0` (block all) for non-exempt users with no allowed profiles --
    safer default than leaking data.
    """
    if _is_exempt(user):
        return ""
    profiles = _allowed_profiles(user)
    if not profiles:
        # Non-exempt user with no User Permission rows -> deny by default.
        return "1=0"
    return f"`{table}`.`{field}` IN {_sql_in_clause(profiles)}"


def _has_perm_by_profile(doc, user: str, profile_field: str = "pos_profile") -> bool:
    if _is_exempt(user):
        return True
    # Owners always retain access to their own docs (covers a cashier
    # editing the shift they themselves opened).
    if getattr(doc, "owner", None) == user:
        return True
    profiles = set(_allowed_profiles(user))
    if not profiles:
        return False
    return getattr(doc, profile_field, None) in profiles


# --- POS Opening Shift ------------------------------------------------------

def pos_opening_shift_query(user: str) -> str:
    return _query_by_profile_field(user, "tabPOS Opening Shift", "pos_profile")


def pos_opening_shift_has_perm(doc, user: str = None, permission_type: str = None) -> bool:
    user = user or frappe.session.user
    return _has_perm_by_profile(doc, user, "pos_profile")


# --- POS Closing Shift ------------------------------------------------------

def pos_closing_shift_query(user: str) -> str:
    return _query_by_profile_field(user, "tabPOS Closing Shift", "pos_profile")


def pos_closing_shift_has_perm(doc, user: str = None, permission_type: str = None) -> bool:
    user = user or frappe.session.user
    return _has_perm_by_profile(doc, user, "pos_profile")


# --- POS Invoice ------------------------------------------------------------

def pos_invoice_query(user: str) -> str:
    return _query_by_profile_field(user, "tabPOS Invoice", "pos_profile")


def pos_invoice_has_perm(doc, user: str = None, permission_type: str = None) -> bool:
    user = user or frappe.session.user
    return _has_perm_by_profile(doc, user, "pos_profile")
