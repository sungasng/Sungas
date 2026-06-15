"""sungas.payroll.bank_upload
==============================

Generates per-bank salary upload files (.xlsx) for a given Payroll Entry.

Replaces the prior on-bench step6b CSV generators with a versioned, in-app
implementation that fixes the leading-zeros bug: bank codes and account
numbers are written as text-formatted cells so Excel does NOT strip the
leading zeros when finance opens / re-saves the file.

Supported banks (drop-in extensible -- add a new builder + register in
SUPPORTED_BANKS):

  - Stanbic IBTC (000221)        -- xlsx, 6 columns
  - Fidelity Bank (000007)       -- xlsx, 5 columns

Usage (Frappe Desk button on Payroll Entry, or via API):

  bench --site <site> execute \\
    "sungas.payroll.bank_upload.generate_bank_upload" \\
    --kwargs "{'payroll_entry': 'HR-PRUN-2026-00002', 'bank': 'stanbic'}"

The function returns a public file URL (saved as a File doc, scoped to the
Payroll Entry). The endpoint is also whitelisted so a button on the
Payroll Entry form can call it directly.
"""
from __future__ import annotations

import io
from typing import Optional

import frappe
from frappe import _
from frappe.utils import flt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Bank registry
# ---------------------------------------------------------------------------

SUPPORTED_BANKS = {
    "stanbic": {
        "label": "Stanbic IBTC",
        "filename_prefix": "stanbic_salary",
    },
    "fidelity": {
        "label": "Fidelity Bank",
        "filename_prefix": "fidelity_salary",
    },
}


# ---------------------------------------------------------------------------
# Salary slip row resolver
# ---------------------------------------------------------------------------

def _resolve_bank_code_field() -> str:
    """Return the field on Bank doctype that holds the NIBSS / clearing code.

    Different Frappe versions + custom-field setups use different field
    names. Probe known candidates in priority order and cache the result.
    """
    cached = frappe.local.cache.get("sungas_bank_code_field") if hasattr(frappe.local, "cache") else None
    if cached:
        return cached

    meta = frappe.get_meta("Bank")
    candidates = (
        "bank_code",
        "nibss_code",
        "custom_nibss_code",
        "clearing_code",
        "swift_number",
        "branch_code",
    )
    for candidate in candidates:
        if meta.has_field(candidate):
            try:
                frappe.local.cache["sungas_bank_code_field"] = candidate
            except Exception:
                pass
            return candidate

    frappe.throw(frappe._(
        "Could not find a NIBSS-code field on the Bank doctype. "
        "Looked for: {0}. Add a custom field named 'nibss_code' (Data) on "
        "the Bank doctype and populate it for each bank.").format(", ".join(candidates)))


def _get_payroll_rows(payroll_entry_name: str, include_draft: bool = False) -> list[dict]:
    """Return one row per submitted Salary Slip linked to the Payroll Entry.

    Each row carries the fields each bank format needs:
      - employee_name (full name)
      - bank_name             (Bank doctype name, e.g. "Stanbic IBTC")
      - bank_ac_no            (10-digit account number, may have leading zero)
      - nibss_code            (6-digit NIBSS code, e.g. "000221")
      - net_pay               (Currency, NGN)

    Validation:
      - Skips slips with missing bank_name / bank_ac_no / NIBSS code; logs a
        warning so finance can fix Employee records before re-running.
      - Skips slips with net_pay <= 0.
    """
    if not frappe.db.exists("Payroll Entry", payroll_entry_name):
        frappe.throw(_("Payroll Entry {0} does not exist").format(payroll_entry_name))

    docstatus_filter = [["docstatus", "in", [0, 1] if include_draft else [1]]]
    slips = frappe.get_all(
        "Salary Slip",
        filters=[
            ["payroll_entry", "=", payroll_entry_name],
            *docstatus_filter,
        ],
        fields=["name", "employee", "employee_name", "bank_name", "bank_account_no", "net_pay"],
        order_by="employee_name asc",
    )

    bank_code_field = _resolve_bank_code_field()

    rows = []
    skipped = []
    for s in slips:
        if flt(s.net_pay) <= 0:
            continue

        # Resolve bank fields directly from Employee if the slip didn't snapshot them.
        bank_name = s.bank_name
        bank_ac_no = s.bank_account_no
        if not bank_name or not bank_ac_no:
            emp = frappe.db.get_value(
                "Employee", s.employee, ["bank_name", "bank_ac_no"], as_dict=True
            )
            if emp:
                bank_name = bank_name or emp.bank_name
                bank_ac_no = bank_ac_no or emp.bank_ac_no

        if not bank_name or not bank_ac_no:
            skipped.append((s.employee_name, "missing bank details"))
            continue

        # Look up the 6-digit NIBSS code on the Bank doctype.
        nibss_code = frappe.db.get_value("Bank", bank_name, bank_code_field) or ""
        if not nibss_code:
            skipped.append((s.employee_name, f"no NIBSS code for bank {bank_name}"))
            continue

        # Normalise: bank code 6-char, account number string preserve leading zeros.
        nibss_code = str(nibss_code).strip().zfill(6)
        bank_ac_no = str(bank_ac_no).strip()

        rows.append({
            "employee_name": (s.employee_name or "").upper(),
            "bank_name": bank_name,
            "bank_ac_no": bank_ac_no,
            "nibss_code": nibss_code,
            "net_pay": flt(s.net_pay),
        })

    if skipped:
        for name, reason in skipped:
            frappe.log_error(
                title="Bank Upload — skipped employee",
                message=f"Payroll Entry: {payroll_entry_name}\n{name}: {reason}",
            )

    return rows


def _filter_rows_for_bank(rows: list[dict], bank_filter_key: str) -> list[dict]:
    """Return only the rows where the employee's bank matches the target.

    Matches loosely on `bank_name` (case-insensitive contains-style).
    """
    needle = bank_filter_key.lower()
    return [
        r for r in rows
        if needle in (r["bank_name"] or "").lower()
    ]


# ---------------------------------------------------------------------------
# Stanbic builder
# ---------------------------------------------------------------------------

def _build_stanbic_xlsx(rows: list[dict], narration: str) -> bytes:
    """Build the Stanbic-format .xlsx with leading-zero-safe text columns.

    Columns:
      A. Reciever Name        (Text)
      B. Reciever Account No  (Text  -- leading zeros preserved)
      C. Amount               (Number)
      D. Sender Narration     (Text)
      E. Receiever's Narration (Text)
      F. BankCode             (Text -- 6-digit NIBSS, leading zeros preserved)
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Salary"

    headers = [
        "Reciever Name",
        "Reciever Account No",
        "Amount",
        "Sender Narration",
        "Receiever's Narration",
        "BankCode",
    ]

    # Header row -- bold + light fill
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    for r_idx, row in enumerate(rows, start=2):
        ws.cell(row=r_idx, column=1, value=row["employee_name"])

        c_acct = ws.cell(row=r_idx, column=2, value=row["bank_ac_no"])
        c_acct.number_format = "@"  # Force text -- preserves leading zeros

        c_amt = ws.cell(row=r_idx, column=3, value=row["net_pay"])
        c_amt.number_format = "#,##0.00"

        ws.cell(row=r_idx, column=4, value=narration)
        ws.cell(row=r_idx, column=5, value=narration)

        c_bank = ws.cell(row=r_idx, column=6, value=row["nibss_code"])
        c_bank.number_format = "@"  # Text format -- preserves leading zeros

    # Auto-fit column widths (approximate)
    for col_idx, h in enumerate(headers, start=1):
        col_letter = get_column_letter(col_idx)
        max_len = max(
            [len(str(h))] + [len(str(ws.cell(row=r_idx + 2, column=col_idx).value or "")) for r_idx in range(len(rows))]
        )
        ws.column_dimensions[col_letter].width = max_len + 2

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fidelity builder
# ---------------------------------------------------------------------------

def _build_fidelity_xlsx(rows: list[dict], narration: str) -> bytes:
    """Build the Fidelity-format .xlsx with leading-zero-safe text columns.

    Columns (5):
      A. Beneficiary Bank Code        (Text, 6-digit NIBSS)
      B. Beneficiary Account Number   (Text, leading zeros preserved)
      C. Beneficiary Name             (Text)
      D. Amount                       (Number)
      E. Narration                    (Text, 5-47 chars per Fidelity spec)
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Salary"

    headers = [
        "Beneficiary Bank Code",
        "Beneficiary Account Number",
        "Beneficiary Name",
        "Amount",
        "Narration",
    ]

    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    # Clamp narration to 47 chars (Fidelity spec: 5-47 inclusive).
    nar = (narration or "")[:47]
    if len(nar) < 5:
        nar = (nar + " " * 5)[:5]

    for r_idx, row in enumerate(rows, start=2):
        c_bank = ws.cell(row=r_idx, column=1, value=row["nibss_code"])
        c_bank.number_format = "@"

        c_acct = ws.cell(row=r_idx, column=2, value=row["bank_ac_no"])
        c_acct.number_format = "@"

        ws.cell(row=r_idx, column=3, value=row["employee_name"])

        c_amt = ws.cell(row=r_idx, column=4, value=row["net_pay"])
        c_amt.number_format = "#,##0.00"

        ws.cell(row=r_idx, column=5, value=nar)

    for col_idx, h in enumerate(headers, start=1):
        col_letter = get_column_letter(col_idx)
        max_len = max(
            [len(str(h))] + [len(str(ws.cell(row=r_idx + 2, column=col_idx).value or "")) for r_idx in range(len(rows))]
        )
        ws.column_dimensions[col_letter].width = max_len + 2

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


BUILDERS = {
    "stanbic": _build_stanbic_xlsx,
    "fidelity": _build_fidelity_xlsx,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@frappe.whitelist()
def generate_bank_upload(
    payroll_entry: str,
    bank: str,
    narration: Optional[str] = None,
    include_draft: int = 0,
) -> dict:
    """Generate the bank-specific salary upload file for a Payroll Entry.

    :param payroll_entry: Payroll Entry name (e.g. "HR-PRUN-2026-00001")
    :param bank: one of "stanbic", "fidelity" (lower case)
    :param narration: text narration (defaults to "PAYMENT OF <Month> <Year> SALARY")
    :param include_draft: if 1, include unsubmitted (draft) Salary Slips too.
                          Defaults to 0 (submitted only). Used for parallel dry runs.
    :return: { "file_url": "/private/files/...", "file_name": "...", "row_count": N }
    """
    bank_key = (bank or "").lower().strip()
    if bank_key not in SUPPORTED_BANKS:
        frappe.throw(_("Unsupported bank '{0}'. Supported: {1}").format(
            bank, ", ".join(SUPPORTED_BANKS.keys())
        ))

    include_draft = bool(int(include_draft or 0))

    all_rows = _get_payroll_rows(payroll_entry, include_draft=include_draft)
    bank_rows = _filter_rows_for_bank(all_rows, bank_key)

    if not bank_rows:
        frappe.throw(_(
            "No Salary Slips with bank matching '{0}' found on Payroll Entry {1}. "
            "Check the Employee bank_name field for each affected employee."
        ).format(bank_key, payroll_entry))

    # Default narration
    pe_meta = frappe.db.get_value(
        "Payroll Entry", payroll_entry,
        ["start_date", "end_date", "posting_date"], as_dict=True,
    )
    if not narration:
        # e.g. "PAYMENT OF MAY 2026 SALARY"
        ref = pe_meta.start_date or pe_meta.posting_date
        if ref:
            narration = f"PAYMENT OF {ref.strftime('%B').upper()} {ref.year} SALARY"
        else:
            narration = f"PAYMENT FROM PAYROLL ENTRY {payroll_entry}"

    builder = BUILDERS[bank_key]
    xlsx_bytes = builder(bank_rows, narration)

    # Save as a File doc attached to the Payroll Entry
    spec = SUPPORTED_BANKS[bank_key]
    filename = f"{spec['filename_prefix']}_{payroll_entry}.xlsx"
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": xlsx_bytes,
        "is_private": 1,
        "attached_to_doctype": "Payroll Entry",
        "attached_to_name": payroll_entry,
    })
    file_doc.flags.ignore_permissions = True
    file_doc.save()

    return {
        "file_url": file_doc.file_url,
        "file_name": filename,
        "row_count": len(bank_rows),
        "bank": spec["label"],
        "narration": narration,
    }
