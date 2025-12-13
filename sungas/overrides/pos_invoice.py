import frappe
from frappe.query_builder.functions import IfNull, Sum
from erpnext.accounts.doctype.pos_invoice.pos_invoice import POSInvoice
from frappe.utils import flt


class POSInvoiceOverride(POSInvoice):
	
	def validate_pos_opening_entry(self):
		opening_entries = frappe.get_list(
			"POS Opening Shift", filters={"pos_profile": self.pos_profile, "status": "Open", "docstatus": 1}
		)
		if len(opening_entries) == 0:
			frappe.throw(
				title=_("POS Opening Shift Missing"),
				msg=_("No open POS Opening Shift found for POS Profile {0}.").format(
					frappe.bold(self.pos_profile)
				),
			)

	def validate_stock_availablility(self):
		if self.is_return:
			return

		if self.docstatus == 0 and not frappe.db.get_value(
			"POS Profile", self.pos_profile, "validate_stock_on_save"
		):
			return

		allow_negative_stock = frappe.db.get_single_value(
			"Stock Settings", "allow_negative_stock"
		)

		for d in self.get("items"):
			if d.serial_no:
				self.validate_pos_reserved_serial_nos(d)
				self.validate_delivered_serial_nos(d)
				self.validate_invalid_serial_nos(d)
			elif d.batch_no:
				self.validate_pos_reserved_batch_qty(d)
			else:
				if allow_negative_stock:
					return

				available_stock, is_stock_item = get_stock_availability(
					d.item_code, d.warehouse
				)

				item_code, warehouse, qty = (
					frappe.bold(d.item_code),
					frappe.bold(d.warehouse),
					frappe.bold(d.qty),
				)
				# if is_stock_item and flt(available_stock) <= 0:
				# 	frappe.throw(
				# 		"Row #{}: Item Code: {} is not available under warehouse {}."
				# 		.format(
				# 			d.idx, item_code, warehouse
				# 		),
				# 		title="Item Unavailable",
				# 	)
				# elif is_stock_item and flt(available_stock) < flt(d.stock_qty):
				# 	frappe.throw(
				# 		"Row #{}: Stock quantity not enough for Item Code: {} under warehouse {}. Available quantity {}."
				# 		.format(d.idx, item_code, warehouse, available_stock),
				# 		title="Item Unavailable",
				# 	)


def get_bin_qty(item_code, warehouse):
	bin_qty = frappe.db.sql(
		"""select actual_qty from `tabBin`
		where item_code = %s and warehouse = %s
		limit 1""",
		(item_code, warehouse),
		as_dict=1,
	)
	return bin_qty[0].actual_qty or 0 if bin_qty else 0


def get_bundle_availability(bundle_item_code, warehouse):
	product_bundle = frappe.get_doc("Product Bundle", bundle_item_code)
	bundle_bin_qty = 1000000
	for item in product_bundle.items:
		item_bin_qty = get_bin_qty(item.item_code, warehouse)
		item_pos_reserved_qty = get_pos_reserved_qty(item.item_code, warehouse)
		available_qty = item_bin_qty - item_pos_reserved_qty

		max_available_bundles = available_qty / item.qty
		if bundle_bin_qty > max_available_bundles and frappe.get_value(
			"Item", item.item_code, "is_stock_item"
		):
			bundle_bin_qty = max_available_bundles

	pos_sales_qty = get_pos_reserved_qty(bundle_item_code, warehouse)
	return bundle_bin_qty - pos_sales_qty


@frappe.whitelist()
def get_stock_availability(item_code, warehouse):
	if frappe.db.get_value("Item", item_code, "is_stock_item"):
		is_stock_item = True
		bin_qty = get_bin_qty(item_code, warehouse)
		pos_sales_qty = get_pos_reserved_qty(item_code, warehouse)
		return bin_qty - pos_sales_qty, is_stock_item
	else:
		is_stock_item = True
		if frappe.db.exists("Product Bundle", item_code):
			return get_bundle_availability(item_code, warehouse), is_stock_item
		else:
			is_stock_item = False
			# Is a service item or non_stock item
			return 0, is_stock_item


def get_pos_reserved_qty(item_code, warehouse):
	p_inv = frappe.qb.DocType("POS Invoice")
	p_item = frappe.qb.DocType("POS Invoice Item")

	reserved_qty = (
		frappe.qb.from_(p_inv)
		.from_(p_item)
		.select(Sum(p_item.qty).as_("qty"))
		.where(
			(p_inv.name == p_item.parent)
			& (IfNull(p_inv.consolidated_invoice, "") == "")
			& (p_inv.is_return == 0)
			& (p_item.docstatus == 1)
			& (p_item.item_code == item_code)
			& (p_item.warehouse == warehouse)
		)
	).run(as_dict=True)

	return reserved_qty[0].qty or 0 if reserved_qty else 0
