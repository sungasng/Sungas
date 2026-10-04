"""Patch 0014b -- in-place editor for sungas/fixtures/server_script.json.

Updates 3 existing Server Scripts to nudge posting_time, and inserts 1 new
Server Script (Before Submit on Stock Entry) that acts as a defensive guard
against human-triggered multi-drop timestamp collisions.
"""
from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "sungas/fixtures/server_script.json"


def _indent(body: str, spaces: int) -> str:
    """Indent every line (including the first) by `spaces` spaces."""
    pad = " " * spaces
    return "\n".join(pad + ln if ln else ln for ln in body.splitlines()) + "\n"


# Helper function body -- plain Python, no leading indent.
NUDGE_HELPER_RAW = (
    "def _p0014b_nudge(ts, seconds):\n"
    "    # ts is 'HH:MM:SS' or 'HH:MM:SS.ffffff'; return a nudged HH:MM:SS\n"
    "    # clamped to 23:59:59.\n"
    "    if not ts:\n"
    "        ts = '00:00:00'\n"
    "    parts = str(ts).split(':')\n"
    "    hh = int(parts[0]); mm = int(parts[1]); ss = int(float(parts[2]))\n"
    "    total = hh * 3600 + mm * 60 + ss + int(seconds)\n"
    "    if total >= 86400:\n"
    "        total = 86399\n"
    "    nh = total // 3600\n"
    "    nm = (total % 3600) // 60\n"
    "    nss = total % 60\n"
    "    return '%02d:%02d:%02d' % (nh, nm, nss)"
)

# ---------------------------------------------------------------------------
# Patch 1 -- "Outlet SE Open Transit Loss Case" (helper block indented 8 spaces)
# ---------------------------------------------------------------------------
PATCH1_OLD = "clear_se.pr_waybill_number = pr.get('waybill_number')\n"
PATCH1_NEW = (
    "clear_se.pr_waybill_number = pr.get('waybill_number')\n"
    "        # Patch 0014b -- nudge posting_time +1s so Frappe reads GIT balance\n"
    "        # AFTER the plant SE committed, not simultaneously (which reads 0).\n"
    + _indent(NUDGE_HELPER_RAW, 8)
    + "        clear_se.posting_date = doc.posting_date\n"
    "        clear_se.posting_time = _p0014b_nudge(doc.posting_time, 1)\n"
)

# ---------------------------------------------------------------------------
# Patch 2 -- "Inter-Outlet Open Variance Case on Receipt" (indent 8)
# ---------------------------------------------------------------------------
PATCH2_OLD = (
    "clearing.posting_date = doc.posting_date\n"
    "        clearing.set_posting_time = 1\n"
)
PATCH2_NEW = (
    "clearing.posting_date = doc.posting_date\n"
    "        clearing.set_posting_time = 1\n"
    "        # Patch 0014b -- nudge posting_time +1s so Frappe reads GIT balance\n"
    "        # AFTER the receiving SE committed, not simultaneously (which reads 0).\n"
    + _indent(NUDGE_HELPER_RAW, 8)
    + "        clearing.posting_time = _p0014b_nudge(doc.posting_time, 1)\n"
)

# ---------------------------------------------------------------------------
# Patch 3 -- "Inter-Outlet Auto-Receipt and Notify" (indent 4)
# ---------------------------------------------------------------------------
PATCH3_OLD = (
    "receipt.transfer_purpose = doc.get('transfer_purpose')\n"
    "    receipt.set_posting_time = 1\n"
)
PATCH3_NEW = (
    "receipt.transfer_purpose = doc.get('transfer_purpose')\n"
    "    receipt.set_posting_time = 1\n"
    "    # Patch 0014b -- nudge receiving SE's posting_time +60s past the dispatch,\n"
    "    # so when the receiving outlet submits immediately, Frappe's stock\n"
    "    # ledger sees GIT populated before the drain.\n"
    + _indent(NUDGE_HELPER_RAW, 4)
    + "    receipt.posting_date = doc.posting_date\n"
    "    receipt.posting_time = _p0014b_nudge(doc.posting_time, 60)\n"
)

# ---------------------------------------------------------------------------
# Patch 4 -- NEW Server Script
# ---------------------------------------------------------------------------
NEW_SCRIPT = {
    "allow_guest": 0,
    "api_method": None,
    "cron_format": None,
    "disabled": 0,
    "doctype": "Server Script",
    "doctype_event": "Before Submit",
    "enable_rate_limit": 0,
    "event_frequency": "All",
    "module": None,
    "name": "SE Transit Posting-Time Collision Guard",
    "rate_limit_count": 5,
    "rate_limit_seconds": 86400,
    "reference_doctype": "Stock Entry",
    "script": (
        "# Patch 0014b -- Posting-Time Collision Guard.\n"
        "# When 2+ operators submit sibling multi-drop receiving SEs at the SAME\n"
        "# wall-clock second, Frappe's stock ledger reads GIT balance as 0 for\n"
        "# the second submitter and throws 'Insufficient Stock'. This guard\n"
        "# detects the collision and auto-nudges this doc's posting_time to\n"
        "# max(sibling_posting_time) + 1 second so the ledger has an\n"
        "# unambiguous order.\n"
        "#\n"
        "# Applies to Stock Entries that reference:\n"
        "#   - outgoing_stock_entry (inter-outlet multi-drop pattern), OR\n"
        "#   - pr_reference_new / pr_reference (PR -> outlet discharge pattern)\n"
        "#\n"
        "# Safe: never raises. Nudges silently; the operator sees their SE submit.\n"
        + NUDGE_HELPER_RAW + "\n"
        "def _p0014b_time_to_sec(ts):\n"
        "    if not ts:\n"
        "        return 0\n"
        "    parts = str(ts).split(':')\n"
        "    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))\n"
        "sibling_filters = None\n"
        "if doc.get('outgoing_stock_entry'):\n"
        "    sibling_filters = {\n"
        "        'outgoing_stock_entry': doc.outgoing_stock_entry,\n"
        "        'posting_date': doc.posting_date,\n"
        "        'docstatus': 1,\n"
        "        'name': ['!=', doc.name],\n"
        "    }\n"
        "elif doc.get('pr_reference_new'):\n"
        "    sibling_filters = {\n"
        "        'pr_reference_new': doc.pr_reference_new,\n"
        "        'posting_date': doc.posting_date,\n"
        "        'docstatus': 1,\n"
        "        'name': ['!=', doc.name],\n"
        "    }\n"
        "elif doc.get('pr_reference'):\n"
        "    sibling_filters = {\n"
        "        'pr_reference': doc.pr_reference,\n"
        "        'posting_date': doc.posting_date,\n"
        "        'docstatus': 1,\n"
        "        'name': ['!=', doc.name],\n"
        "    }\n"
        "if sibling_filters:\n"
        "    siblings = frappe.get_all('Stock Entry',\n"
        "        filters=sibling_filters,\n"
        "        fields=['name', 'posting_time'])\n"
        "    if siblings:\n"
        "        max_sec = 0\n"
        "        max_name = None\n"
        "        for sib in siblings:\n"
        "            s = _p0014b_time_to_sec(sib.get('posting_time'))\n"
        "            if s > max_sec:\n"
        "                max_sec = s\n"
        "                max_name = sib.get('name')\n"
        "        this_sec = _p0014b_time_to_sec(doc.posting_time)\n"
        "        if this_sec <= max_sec:\n"
        "            new_ts = _p0014b_nudge(doc.posting_time, (max_sec - this_sec) + 1)\n"
        "            doc.set_posting_time = 1\n"
        "            doc.posting_time = new_ts\n"
        "            frappe.log_error(\n"
        "                title='SE Posting-Time Collision Auto-Nudged',\n"
        "                message=('SE %s: posting_time collided with sibling %s. '\n"
        "                         'Auto-nudged to %s to preserve stock-ledger ordering.'\n"
        "                        ) % (doc.name or 'new', max_name, new_ts)\n"
        "            )\n"
    ),
    "script_type": "DocType Event",
}


def main() -> None:
    data = json.loads(FIXTURE.read_text())

    targets = {
        "Outlet SE Open Transit Loss Case": (PATCH1_OLD, PATCH1_NEW),
        "Inter-Outlet Open Variance Case on Receipt": (PATCH2_OLD, PATCH2_NEW),
        "Inter-Outlet Auto-Receipt and Notify": (PATCH3_OLD, PATCH3_NEW),
    }
    patched = {k: False for k in targets}

    for entry in data:
        name = entry.get("name")
        if name in targets:
            old, new = targets[name]
            script = entry["script"]
            if "Patch 0014b" in script:
                patched[name] = True
                continue
            if old not in script:
                raise SystemExit(f"ERROR: anchor missing in {name!r}")
            entry["script"] = script.replace(old, new, 1)
            patched[name] = True

    for name, ok in patched.items():
        if not ok:
            raise SystemExit(f"ERROR: never located fixture entry {name!r}")

    names = {e.get("name") for e in data}
    if NEW_SCRIPT["name"] not in names:
        data.append(NEW_SCRIPT)

    FIXTURE.write_text(json.dumps(data, indent=1) + "\n")
    print("[Patch 0014b] fixtures updated OK")


if __name__ == "__main__":
    main()
