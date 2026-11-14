from frappe.model.document import Document

from sungas import shift_controls


class SungasCashLodgement(Document):
    def validate(self):
        shift_controls.validate_lodgement(self)

    def before_submit(self):
        shift_controls.before_submit_lodgement(self)

    def on_submit(self):
        shift_controls.on_submit_lodgement(self)

    def on_cancel(self):
        shift_controls.on_cancel_lodgement(self)
