# Copyright (c) 2013, Manqala and contributors
# For license information, please see license.txt

from datetime import date
import frappe
from frappe import _

def execute(filters=None):
	columns, data = get_columns(filters), fetch_data(filters)
	return columns, data
	
def get_columns(filters):
	cols= [
			{
			"label": _("Item Code"),
			"fieldtype": "Link",
			"options":"Item",
			"fieldname": "item_code",
			"width": 120
			},
			{
			"label": _("Item Name"),
			"fieldtype": "Data",
			"fieldname": "item_name",
			"width": 120
			},
			{
			"label": _("Item Group"),
			"fieldtype": "Link",
			"options":"Item Group",
			"fieldname": "item_group",
			"width": 120
			},
			{
			"label": _("Invoice"),
			"fieldtype": "Link",
			"options":"Sales Invoice",
			"fieldname": "sales_invoice",
			"width": 120
			},
			{
			"label": _("Posting Date"),
			"fieldtype": "Date",
			"fieldname": "p_date",
			"width": 120
			},
			{
			"label": _("Customer Name"),
			"fieldtype": "Data",
			"fieldname": "c_name",
			"width": 120
			},
			{
			"label": _("Customer Group"),
			"fieldtype": "Link",
			"fieldname": "c_group",
			"options":"Customer Group",
			"width": 120
			},
			{
			"label": _("Territory"),
			"fieldtype": "Link",
			"options":"Territory",
			"fieldname": "territory",
			"width": 120
			},
			{
			"label": _("Cost Center"),
			"fieldtype": "Link",
			"options":"Cost Center",
			"fieldname": "c_center",
			"width": 120
			},
			{
			"label": _("Stock Qty"),
			"fieldtype": "Float",
			"fieldname": "s_qty",
			"width": 120
			},
			{
			"label": _("Stock UOM"),
			"fieldtype": "Link",
			"options":"UOM",
			"fieldname": "s_uom",
			"width": 120
			},
			{
			"label": _("Stock in KG"),
			"fieldtype": "Float",
			"fieldname": "s_i_kg",
			"width": 120
			},
			{
			"label": _("Created By"),
			"fieldtype": "data",
			"fieldname": "created_by",
			"width": 120
			},
			{
			"label": _("Rate"),
			"fieldtype": "Currency",
			"fieldname": "i_rate",
			"width": 120
			},
			{
			"label": _("Amount"),
			"fieldtype": "Currency",
			"fieldname": "i_amount",
			"width": 120
			},
			{
			"label": _("Total Tax"),
			"fieldtype": "Currency",
			"fieldname": "i_t_tax",
			"width": 120
			},
			{
			"label": _("Total"),
			"fieldtype": "Currency",
			"fieldname": "i_total",
			"width": 120
			},
			{
			"label": _("Currency"),
			'options':'Currency',
			"fieldtype": "Link",
			"fieldname": "currency",
			"width": 90
			},
			]
	return cols



def update_product_bundle(one,pack,sales_inv_deets,c_group,inv,tax):
	#Remove product bundle items and replce them with the individual product.
	data = {}
	for i in pack:
		if one['item_code'] == i:
			conv_qty = frappe.get_all("Product Bundle Item",{'parent':i},['item_code','qty','uom'])[0]
			data = {
				'item_code':one['item_code'],
				'item_name':one['item_name'],
				'item_group':one['item_group'],
				'sales_invoice':inv,
				'p_date':sales_inv_deets[0]['posting_date'],
				'c_name':sales_inv_deets[0]['customer_name'],
				'c_group':c_group,
				'territory':sales_inv_deets[0]['territory'],
				'c_center':one['cost_center'],
				's_qty':one['stock_qty'],
				's_uom':one['stock_uom'],
				's_i_kg':conv_qty['qty']*one['stock_qty'],
				'created_by':sales_inv_deets[0]['owner'],
				'i_rate':one['base_rate'],
				'i_amount':one['base_amount'],
				'i_t_tax':tax,
				'i_total':tax+one['base_amount'],
				'currency':sales_inv_deets[0]['currency']
			}
			
	return data

def fetch_tax_amount(row,inv):
	#Fetch the item tax amount for the item row.
	total_tax = 0
	if frappe.get_value("Sales Invoice",inv,'taxes_and_charges'):
		tax_details = frappe.get_all("Sales Taxes and Charges",\
			{"parent":frappe.get_value("Sales Invoice",inv,'taxes_and_charges'),'charge_type':"On Net Total"},['rate'])
		if tax_details:
			for one in tax_details:
				total_tax+=((one['rate']/100)*row['base_amount'])
	if row.get('item_tax_template'):
		rates = frappe.get_all('Item Tax Template Detail',{'parent':row.get('item_tax_template')},['tax_rate'])
		if rates:
			for each in rates:
				total_tax+=((each['tax_rate']/100)*row['base_amount'])
	return total_tax


def invoice_details(inv,filters):
	#fetch invoice details from line item of sales invoice.
	data = []
	alL_bundle_items = frappe.get_all("Product Bundle",['new_item_code','name'])
	all_b_items = [i['name'] for i in alL_bundle_items]
	cust = frappe.get_value("Sales Invoice",inv,'customer')
	filter_dict = {'parent':inv}
	if filters.get('warehouse'):
		filter_dict['warehouse']=filters.get('warehouse')
	elif filters.get('item_group'):
		filter_dict['item_group'] = filters.get('item_group')
	item_deets = frappe.get_all("Sales Invoice Item",filter_dict,['item_code',\
		'item_name','item_group','cost_center','stock_uom','rate','amount','item_tax_template',\
		'base_rate','base_amount','stock_qty'])
	sales_inv_deets = frappe.get_all("Sales Invoice",{'name':inv},['territory','customer_name','owner','posting_date','currency'])
	c_group = frappe.get_value("Customer",cust,'customer_group')
	for one in item_deets:
		tax_amount = fetch_tax_amount(one,inv)
		if one['item_code'] not in all_b_items:
		# one = update_product_bundle(one,data)
			data.append({
				'item_code':one['item_code'],
				'item_name':one['item_name'],
				'item_group':one['item_group'],
				'sales_invoice':inv,
				'p_date':sales_inv_deets[0]['posting_date'],
				'c_name':sales_inv_deets[0]['customer_name'],
				'c_group':c_group,
				'territory':sales_inv_deets[0]['territory'],
				'c_center':one['cost_center'],
				's_qty':one['stock_qty'],
				's_uom':one['stock_uom'],
				's_i_kg':one['stock_qty'],
				'created_by':sales_inv_deets[0]['owner'],
				'i_rate':one['base_rate'],
				'i_amount':one['base_amount'],
				'i_t_tax':tax_amount,
				'i_total':tax_amount+one['base_amount'],
				'currency':sales_inv_deets[0]['currency']
			})
		else:
			data.append(update_product_bundle(one,all_b_items,sales_inv_deets,c_group,inv,tax_amount))
	
	return data



def fetch_data(filters):
	data =[]
	#Fetch all pos invoices in date range
	filter_dict={'docstatus':1,\
		'creation':['between',[filters.get('from_date'),filters.get('to_date')]]}
	if filters.get('customer'):
		filter_dict['customer']=filters.get('customer')
	elif filters.get('pos_profile'):
		filter_dict['pos_profile'] = filters.get('pos_profile')
	all_inv = frappe.get_all("Sales Invoice",filter_dict)
	for i in all_inv:
		data+=invoice_details(i['name'],filters)
	return data
	


