"""sungas.install.seed_outlet_managers
========================================

One-shot script that populates `POS Profile.outlet_manager` for every
profile that doesn't have one set.

Resolution strategy:
  1. Look at the POS Profile's `branch` field (HRMS Branch).
  2. Find an active Employee whose `branch` matches and whose
     `designation` is one of: 'Plant Manager', 'Outlet Manager',
     'Plant Head', 'Branch Manager'.
  3. If found and that Employee has a `user_id`, set it as the
     outlet_manager.

Fallback strategy:
  - If branch-based lookup fails, scan the `POS Profile User` child
    table for the first user holding the role 'LPG Plant Manager'.

Idempotent: skips profiles that already have outlet_manager set.

Run with:
    bench --site <site> execute sungas.install.seed_outlet_managers.seed
"""
from __future__ import annotations

import frappe


PLANT_MANAGER_DESIGNATIONS = (
    "Plant Manager",
    "Outlet Manager",
    "Plant Head",
    "Branch Manager",
)


def _find_by_branch(branch: str) -> str | None:
    if not branch:
        return None
    rows = frappe.get_all(
        "Employee",
        filters=[
            ["branch", "=", branch],
            ["designation", "in", list(PLANT_MANAGER_DESIGNATIONS)],
            ["status", "=", "Active"],
        ],
        fields=["user_id"],
        limit=1,
    )
    if rows and rows[0].user_id:
        return rows[0].user_id
    return None


def _find_by_applicable_users(profile_name: str) -> str | None:
    rows = frappe.get_all(
        "POS Profile User",
        filters={"parent": profile_name},
        fields=["user"],
    )
    for r in rows:
        if r.user and "LPG Plant Manager" in frappe.get_roles(r.user):
            return r.user
    return None


def seed():
    profiles = frappe.get_all(
        "POS Profile",
        filters={"disabled": 0},
        fields=["name", "branch", "outlet_manager"],
    )

    stats = {"already_set": 0, "set_by_branch": 0, "set_by_applicable": 0, "unresolved": []}

    for p in profiles:
        if p.outlet_manager:
            stats["already_set"] += 1
            continue

        chosen = _find_by_branch(p.branch)
        if chosen:
            frappe.db.set_value("POS Profile", p.name, "outlet_manager", chosen)
            stats["set_by_branch"] += 1
            print(f"  ✅ {p.name:<35}  outlet_manager = {chosen}  (via branch)")
            continue

        chosen = _find_by_applicable_users(p.name)
        if chosen:
            frappe.db.set_value("POS Profile", p.name, "outlet_manager", chosen)
            stats["set_by_applicable"] += 1
            print(f"  ✅ {p.name:<35}  outlet_manager = {chosen}  (via applicable_users)")
            continue

        stats["unresolved"].append(p.name)
        print(f"  ⚠️  {p.name:<35}  -- could NOT resolve outlet_manager")

    frappe.db.commit()

    print("")
    print("=" * 70)
    print("  Seed complete:")
    print(f"    already set         : {stats['already_set']}")
    print(f"    set via branch      : {stats['set_by_branch']}")
    print(f"    set via applicable  : {stats['set_by_applicable']}")
    print(f"    UNRESOLVED          : {len(stats['unresolved'])}")
    if stats["unresolved"]:
        print("\n  Unresolved profiles need manual outlet_manager assignment:")
        for n in stats["unresolved"]:
            print(f"    - {n}")
    print("=" * 70)

    return stats
