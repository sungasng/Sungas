import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate

from sungas.engagement import EXECUTING, _can_decide, fill_actuals, totals

PLAN_FIELDS = ("customer", "root_cause", "action", "action_due", "expected_kg", "plan_note")
OUTCOME_FIELDS = ("outcome", "outcome_note")


class WeeklyEngagementPlan(Document):
    def validate(self):
        ws = getdate(self.week_start)
        if ws.weekday() != 0:
            frappe.throw(_("Week Starting must be a Monday."))
        self.week_end = add_days(ws, 6)
        for i, line in enumerate(self.lines, 1):
            if line.action_due and not (ws <= getdate(line.action_due) <= getdate(self.week_end)):
                frappe.throw(_("Row {0}: due date must fall inside the plan week ({1} to {2}).").format(
                    i, self.week_start, self.week_end))
        if not self.is_new() and not self.flags.sungas_internal:
            self._guard_edits()
        if self.status in EXECUTING + ("Outcome Reported",):
            fill_actuals(self)
        totals(self)

    def _guard_edits(self):
        before = self.get_doc_before_save()
        if not before:
            return
        if before.status != self.status:
            frappe.throw(_("Use the buttons on the plan to change its status."))
        old = {l.name: l for l in before.lines}
        planning = self.status in ("Draft", "Sent Back")
        outcome = self.status in EXECUTING
        if not planning and (len(old) != len(self.lines) or any(l.name not in old for l in self.lines)):
            frappe.throw(_("Accounts can only be added or removed while the plan is Draft or Sent Back."))
        for line in self.lines:
            prev = old.get(line.name)
            if not prev:
                continue
            if not planning and any(prev.get(f) != line.get(f) for f in PLAN_FIELDS) and not _can_decide():
                frappe.throw(_("The plan is {0}; planning fields are locked.").format(self.status))
            if not outcome and any(prev.get(f) != line.get(f) for f in OUTCOME_FIELDS):
                frappe.throw(_("Outcomes can only be entered once the plan is approved or executing."))
