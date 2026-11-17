"""Patch 0061 -- Driver Liable / Hauler Liable on an IOVC take the driver / hauler from the trip."""
from __future__ import annotations

import frappe


def _trip(doc):
    for se in (doc.get("receipt_entry"), doc.get("dispatch_entry")):
        ls = frappe.db.get_value("Stock Entry", se, "loading_schedule") if se else None
        if ls:
            return frappe.db.get_value("Daily Loading Schedule", ls, ["driver", "hauler"], as_dict=True)
    return None


def fill_from_trip(doc, method=None):
    res = doc.get("resolution")
    need_driver = res == "Driver Liable" and not doc.get("culpable_employee")
    need_hauler = res == "Hauler Liable" and not doc.get("hauler")
    if not (need_driver or need_hauler):
        return
    trip = _trip(doc)
    if not trip:
        return
    if need_driver and trip.driver:
        doc.culpable_employee = trip.driver
    if need_hauler and trip.hauler:
        doc.hauler = trip.hauler
