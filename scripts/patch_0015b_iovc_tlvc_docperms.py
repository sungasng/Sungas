"""Patch 0015b -- git-track Custom DocPerm entries for Inter-Outlet Variance
Case and Transit Loss Variance Case.

Prod incident: Cecilia Mathew (LPG Plant Manager) got 'Not permitted / No
permission for Page' when opening IOVC 1k1ric518e. Earlier the same thing
hit femi.lee@sungas.org (LPG Head of Operations) on TLVC.

Root cause: both doctypes were created via Frappe UI (not git-tracked as
sungas-app doctypes) and their native DocPerms grant access only to roles
that happen to be seeded on the particular user's DB record. There are no
custom_docperm fixtures for them, so every fresh deploy drifts.

Fix: snapshot a canonical set of 7 roles x 2 doctypes = 14 DocPerm entries
and commit them to sungas/fixtures/custom_docperm.json. after_migrate
drift cron (Patch 0013) will warn if any role perm regresses.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "sungas" / "fixtures" / "custom_docperm.json"

TARGETS = ("Inter-Outlet Variance Case", "Transit Loss Variance Case")

# Role -> perm grants. Mirrors the Purchase Order / Purchase Receipt pattern
# (permlevel 0 only). TRUE if the role can perform the action.
ROLE_MATRIX = [
    # (role, read, write, create, submit, cancel, amend, export, report, print, email, share, delete)
    ("System Manager",          1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
    ("LPG Plant Manager",       1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0),  # receiver/originator
    ("LPG Head of Operations",  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0),  # HoD Ops
    ("LPG Head of Finance",     1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0),  # HoF (write-off gate)
    ("COO",                     1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0),  # oversight read-only
    ("Accounts Manager",        1, 1, 0, 0, 1, 0, 1, 1, 1, 1, 1, 0),  # GL reconciliation
    ("Stock Manager",           1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0),  # creates the case from SE
]


def _row(doctype: str, role: str, idx: int, read, write, create, submit, cancel_,
         amend, export_, report, print_, email, share, delete):
    return {
        "amend": amend,
        "cancel": cancel_,
        "create": create,
        "delete": delete,
        "doctype": "Custom DocPerm",
        "email": email,
        "export": export_,
        "if_owner": 0,
        "import": 0,
        "match": None,
        "name": f"{doctype}-{role}-{idx}",
        "parent": doctype,
        "parentfield": "permissions",
        "parenttype": "DocType",
        "permlevel": 0,
        "print": print_,
        "read": read,
        "report": report,
        "role": role,
        "select": 0,
        "set_user_permissions": 0,
        "share": share,
        "submit": submit,
        "write": write,
    }


def main() -> None:
    data = json.loads(FIXTURE.read_text())

    # Strip any pre-existing entries for our two target doctypes so re-runs
    # replace rather than duplicate.
    data = [e for e in data if e.get("parent") not in TARGETS]

    added = 0
    for doctype in TARGETS:
        for idx, (role, r, w, c, s, cn, a, exp, rep, pr, em, sh, de) in enumerate(ROLE_MATRIX, 1):
            data.append(_row(doctype, role, idx, r, w, c, s, cn, a, exp, rep, pr, em, sh, de))
            added += 1

    FIXTURE.write_text(json.dumps(data, indent=1) + "\n")
    print(f"[Patch 0015b] +{added} Custom DocPerm entries ({len(TARGETS)} doctypes x "
          f"{len(ROLE_MATRIX)} roles). Total fixture entries: {len(data)}")


if __name__ == "__main__":
    main()
