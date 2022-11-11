import frappe
from six import string_types
import json
from frappe.desk.reportview import get_filters_cond
from frappe.utils import (
	add_days,
	add_months,
	cint,
	strip,
	cstr,
	date_diff,
	format_datetime,
	get_datetime,
	get_datetime_str,
	getdate,
	now_datetime,
	nowdate,
)
from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost
from frappe.utils.user import get_enabled_system_users


# frappe.enqueue(repost, timeout=12000, queue='long',
# 			job_name='repost_sle', now=frappe.flags.in_test, doc=self)


weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

@frappe.whitelist()
def get_events(start, end, user=None, for_reminder=False, filters=None):
	if not user:
		user = frappe.session.user

	if isinstance(filters, string_types):
		filters = json.loads(filters)

	filter_condition = get_filters_cond("Event", filters, [])

	tables = ["`tabEvent`"]
	if "`tabEvent Participants`" in filter_condition:
		tables.append("`tabEvent Participants`")

	events = frappe.db.sql(
		"""
		SELECT `tabEvent`.name,
				`tabEvent`.subject,
				`tabEvent`.description,
				`tabEvent`.color,
				`tabEvent`.starts_on,
				`tabEvent`.ends_on,
				`tabEvent`.owner,
				`tabEvent`.all_day,
				`tabEvent`.event_type,
				`tabEvent`.repeat_this_event,
				`tabEvent`.repeat_on,
				`tabEvent`.repeat_till,
				`tabEvent`.monday,
				`tabEvent`.tuesday,
				`tabEvent`.wednesday,
				`tabEvent`.thursday,
				`tabEvent`.friday,
				`tabEvent`.saturday,
				`tabEvent`.sunday
		FROM {tables}
		WHERE (
				(
					(date(`tabEvent`.starts_on) BETWEEN date(%(start)s) AND date(%(end)s))
					OR (date(`tabEvent`.ends_on) BETWEEN date(%(start)s) AND date(%(end)s))
					OR (
						date(`tabEvent`.starts_on) <= date(%(start)s)
						AND date(`tabEvent`.ends_on) >= date(%(end)s)
					)
				)
				OR (
					date(`tabEvent`.starts_on) <= date(%(start)s)
					AND `tabEvent`.repeat_this_event=1
					AND coalesce(`tabEvent`.repeat_till, '3000-01-01') > date(%(start)s)
				)
			)
		{reminder_condition}
		{filter_condition}
		AND (
				`tabEvent`.event_type='Private'
				OR `tabEvent`.owner=%(user)s
				OR EXISTS(
					SELECT `tabDocShare`.name
					FROM `tabDocShare`
					WHERE `tabDocShare`.share_doctype='Event'
						AND `tabDocShare`.share_name=`tabEvent`.name
						AND `tabDocShare`.user=%(user)s
				)
			)
		AND `tabEvent`.status='Open'
		ORDER BY `tabEvent`.starts_on""".format(
			tables=", ".join(tables),
			filter_condition=filter_condition,
			reminder_condition="AND coalesce(`tabEvent`.send_reminder, 0)=1" if for_reminder else "",
		),
		{
			"start": start,
			"end": end,
			"user": user,
		},
		as_dict=1,
	)

	# process recurring events
	start = start.split(" ")[0]
	end = end.split(" ")[0]
	add_events = []
	remove_events = []

	def add_event(e, date):
		new_event = e.copy()

		enddate = (
			add_days(date, int(date_diff(e.ends_on.split(" ")[0], e.starts_on.split(" ")[0])))
			if (e.starts_on and e.ends_on)
			else date
		)

		new_event.starts_on = date + " " + e.starts_on.split(" ")[1]
		new_event.ends_on = new_event.ends_on = (
			enddate + " " + e.ends_on.split(" ")[1] if e.ends_on else None
		)

		add_events.append(new_event)

	for e in events:
		if e.repeat_this_event:
			e.starts_on = get_datetime_str(e.starts_on)
			e.ends_on = get_datetime_str(e.ends_on) if e.ends_on else None

			event_start, time_str = get_datetime_str(e.starts_on).split(" ")

			repeat = "3000-01-01" if cstr(e.repeat_till) == "" else e.repeat_till

			if e.repeat_on == "Yearly":
				start_year = cint(start.split("-")[0])
				end_year = cint(end.split("-")[0])

				# creates a string with date (27) and month (07) eg: 07-27
				event_start = "-".join(event_start.split("-")[1:])

				# repeat for all years in period
				for year in range(start_year, end_year + 1):
					date = str(year) + "-" + event_start
					if (
						getdate(date) >= getdate(start)
						and getdate(date) <= getdate(end)
						and getdate(date) <= getdate(repeat)
					):
						add_event(e, date)

				remove_events.append(e)

			if e.repeat_on == "Monthly":
				# creates a string with date (27) and month (07) and year (2019) eg: 2019-07-27
				date = start.split("-")[0] + "-" + start.split("-")[1] + "-" + event_start.split("-")[2]

				# last day of month issue, start from prev month!
				try:
					getdate(date)
				except ValueError:
					date = date.split("-")
					date = date[0] + "-" + str(cint(date[1]) - 1) + "-" + date[2]

				start_from = date
				for i in range(int(date_diff(end, start) / 30) + 3):
					if (
						getdate(date) >= getdate(start)
						and getdate(date) <= getdate(end)
						and getdate(date) <= getdate(repeat)
						and getdate(date) >= getdate(event_start)
					):
						add_event(e, date)

					date = add_months(start_from, i + 1)
				remove_events.append(e)

			if e.repeat_on == "Weekly":
				for cnt in range(date_diff(end, start) + 1):
					date = add_days(start, cnt)
					if (
						getdate(date) >= getdate(start)
						and getdate(date) <= getdate(end)
						and getdate(date) <= getdate(repeat)
						and getdate(date) >= getdate(event_start)
						and e[weekdays[getdate(date).weekday()]]
					):
						add_event(e, date)

				remove_events.append(e)

			if e.repeat_on == "Daily":
				for cnt in range(date_diff(end, start) + 1):
					date = add_days(start, cnt)
					if (
						getdate(date) >= getdate(event_start)
						and getdate(date) <= getdate(end)
						and getdate(date) <= getdate(repeat)
					):
						add_event(e, date)

				remove_events.append(e)

	for e in remove_events:
		events.remove(e)

	events = events + add_events

	for e in events:
		# remove weekday properties (to reduce message size)
		for w in weekdays:
			del e[w]

	return events

def send_event_digest():
	today = nowdate()
	for user in get_enabled_system_users():
		events = get_events(today, today, user.name, for_reminder=True)
		print("EVENTS")
		print(events)
		if events:
			frappe.set_user_lang(user.name, user.language)

			for e in events:
				e.starts_on = format_datetime(e.starts_on, "hh:mm a")
				if e.all_day:
					e.starts_on = "All Day"

			frappe.sendmail(
				recipients=user.email,
				subject=frappe._("Upcoming Events for Today"),
				template="upcoming_events",
				args={
					"events": events,
				},
				header=[frappe._("Events in Today's Calendar"), "blue"],
			)









@frappe.whitelist()
def repost_entry(doc):
	
	doc = frappe.get_doc("Repost Item Valuation",doc)
	frappe.enqueue(repost, timeout=99000, queue='long',job_name='repost_sle', now=frappe.flags.in_test, doc=doc)
	
	return True


def item_name(doc,ev):
	if frappe.db.get_default("item_naming_by") == "Naming Series":
		if doc.variant_of:
			doc.naming_series = frappe.db.get_value("Item",doc.variant_of,'naming_series')
		from frappe.model.naming import set_name_by_naming_series
		set_name_by_naming_series(doc)
		doc.item_code = doc.name


@frappe.whitelist()
def submit_je(doc,ev):
	doc.approving_user = frappe.session.user
	# doc.save()
	

@frappe.whitelist()
def validate_customer(doc,ev):
	#Validate that a customer cannot be created twice within the same territory
	if isinstance(doc,string_types):
		doc=json.loads(doc)
	if doc.is_new():
		exists = frappe.get_all("Customer",{'Territory':doc.territory,'mobile_no':doc.mobile_no})
		if exists:
			frappe.throw(f"Please not that a customer with mobile no {doc.mobile_no} in territory {doc.territory} already exists")


@frappe.whitelist()
def autoname_sales_invoice(doc,ev):
	#Validate that a Sales invoice fetches the naming series from the pos profile
	if isinstance(doc,string_types):
		doc=json.loads(doc)
	if doc.pos_profile:
		prof_doc = frappe.get_doc("POS Profile",doc.pos_profile)
		req_doc = prof_doc.sales_invoice_series or None
		if doc.is_new() and doc.pos_profile :
			doc.naming_series = req_doc
			frappe.db.commit()
			return

def validate_sales_invoice(doc,ev):
	if doc.posa_pos_opening_shift:
		if doc.outstanding_amount > 0.0:
			frappe.throw("Please complete payment for this POS invoice")