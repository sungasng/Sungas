# Copyright (c) 2026, Manqala and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SungasPricingPolicy(Document):
    """Single doctype holding all Pricing Wave configurable thresholds.

    Read by:
      * sungas.overrides.item_pricing_gate (P-7)
      * (future) sungas.scheduled_jobs.margin_band_check (P-9)
      * (future) sungas.scheduled_jobs.lpg_pcr_sla (P-10)
      * (future) sungas.sungas.doctype.bulk_price_upload (P-3)
    """

    pass
