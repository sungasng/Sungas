# Copyright (c) 2026, Manqala and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AnnexT07DenominationRow(Document):
    """Child table row: one NGN denomination on an Annex T-07 cash count.

    Field math is computed by the parent `Annex T-07 Worksheet` controller
    on validate so we don't pay the cost of a per-row before_save event.
    """

    pass
