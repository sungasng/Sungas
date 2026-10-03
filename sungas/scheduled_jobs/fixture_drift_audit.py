"""sungas.scheduled_jobs.fixture_drift_audit
=============================================

Patch 0013 (B) -- Daily cron that detects DB-only edits to
governance artifacts (Server Scripts, Workflows, Custom Fields,
Notifications, Dashboards) that are NOT reflected in the git-tracked
fixture JSON. Logs any drift to Error Log and fires an in-app ToDo
to System Manager users.

Why this exists: the last fixture-sync disaster (Patches 0010-0011)
happened because production had DB-only edits to the Purchase
Receipt workflow + docperms. Fixtures reloaded on migrate wiped
those silently. This cron catches drift the day it happens.

The audit is read-only -- it does not fix drift, only reports it.
Fixing drift is a deliberate human action (export via the governance
exporter, commit, push).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import frappe  # type: ignore

SYS_MGR_ROLE = "System Manager"


def run() -> dict:
    """Scheduler entry-point. Returns a dict summary. Never throws.

    Compares each tracked governance fixture against a fresh dump
    from the DB. Any mismatch is logged + ToDo'd.
    """
    summary = {"audited": 0, "drifted": [], "errors": []}

    try:
        fixtures_dir = Path(frappe.get_app_path("sungas", "fixtures"))

        # Lazy import to avoid circular at module load
        from sungas.utils import export_governance_fixtures as exporter

        with tempfile.TemporaryDirectory(prefix="sungas_drift_") as tmp:
            try:
                exporter.export_all(tmp)
            except Exception:
                summary["errors"].append("exporter_failed")
                frappe.log_error(
                    title="fixture_drift_audit: exporter crashed",
                    message=frappe.get_traceback(),
                )
                return summary

            # Compare each tracked file in the live fixtures dir with the
            # freshly dumped version.
            for live_path in sorted(fixtures_dir.glob("*.json")):
                summary["audited"] += 1
                tmp_path = Path(tmp) / live_path.name
                if not tmp_path.exists():
                    # Live fixture has no DB equivalent (unmanaged or filtered-out)
                    continue
                try:
                    if _normalised(live_path) != _normalised(tmp_path):
                        summary["drifted"].append(live_path.name)
                except Exception:
                    summary["errors"].append(f"compare_failed:{live_path.name}")
                    frappe.log_error(
                        title=f"fixture_drift_audit: compare failed {live_path.name}",
                        message=frappe.get_traceback(),
                    )

        if summary["drifted"]:
            _report(summary["drifted"])

    except Exception:
        frappe.log_error(
            title="fixture_drift_audit crashed",
            message=frappe.get_traceback(),
        )

    return summary


def _normalised(path: Path) -> str:
    """Canonicalise a fixture JSON so field order / whitespace don't
    cause false positives. Lists of docs are sorted by name.
    """
    try:
        data = json.loads(path.read_text())
    except Exception:
        return path.read_text()  # fallback: raw bytes
    if isinstance(data, list):
        data = sorted(
            data,
            key=lambda d: (d.get("doctype", ""), d.get("name", "")) if isinstance(d, dict) else ("", ""),
        )
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def _report(drifted_files: list[str]) -> None:
    """Create an Error Log + ToDo for every active System Manager."""
    body = (
        "The following git-tracked governance fixtures have diverged from "
        "the production DB. Someone edited a DocType in Desk without "
        "committing the export back to git.\n\n"
        + "\n".join(f"  - {f}" for f in drifted_files)
        + "\n\nFix: run `bench --site <site> execute "
          "sungas.utils.export_governance_fixtures.export`, review the "
          "diff, commit to git, and re-deploy. Until then every migrate "
          "risks wiping the DB-only edit silently."
    )

    frappe.log_error(title="FIXTURE DRIFT DETECTED", message=body)

    sm_users = _collect_sys_mgr_users()
    for user in sm_users:
        if frappe.db.exists(
            "ToDo",
            {
                "allocated_to": user,
                "description": ("%" + "FIXTURE DRIFT" + "%"),
                "status": "Open",
            },
        ):
            # Already pending for this user; don't spam
            continue
        try:
            frappe.get_doc({
                "doctype": "ToDo",
                "allocated_to": user,
                "description": (
                    "<b>FIXTURE DRIFT DETECTED</b><br>"
                    f"{len(drifted_files)} governance fixture(s) diverged "
                    "from the production DB. See today's Error Log for "
                    "the list and remediation steps."
                ),
                "priority": "Medium",
                "status": "Open",
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(
                title="fixture_drift_audit: ToDo insert failed",
                message=frappe.get_traceback(),
            )


def _collect_sys_mgr_users() -> list[str]:
    rows = frappe.get_all(
        "Has Role",
        filters={"role": SYS_MGR_ROLE, "parenttype": "User"},
        fields=["parent"],
    )
    out = []
    for r in rows:
        u = r.parent
        if u and "@" in u and u != "Administrator" and u not in out:
            if frappe.db.get_value("User", u, "enabled"):
                out.append(u)
    return out
