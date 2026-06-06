/**
 * Sungas customisation for POS Closing Shift form.
 *
 * 1. Restrict the `variance_approved_by` link to users that hold one of the
 *    approver roles configured on Sungas Close Policy. Falls back to a
 *    static role list if the policy can't be fetched.
 *
 * 2. Inject a banner explaining the variance approval workflow when the
 *    document is a draft with a variance.
 */

// Default approver roles - kept in sync with Sungas Close Policy defaults.
// Used as a safe fallback if the policy single can't be fetched client-side.
const APPROVER_ROLES_DEFAULT = [
    "LPG Head of Operations",
    "Accounts Manager",
    "LPG Head of Finance",
    "System Manager",
];

let _approver_roles_cache = null;

async function get_approver_roles(frm) {
    if (_approver_roles_cache) return _approver_roles_cache;
    try {
        const { message } = await frappe.db.get_value(
            "Sungas Close Policy",
            "Sungas Close Policy",
            ["approver_roles"]
        );
        if (message && message.approver_roles) {
            const roles = message.approver_roles
                .split("\n")
                .map((r) => r.trim())
                .filter(Boolean);
            if (roles.length) {
                _approver_roles_cache = roles;
                return roles;
            }
        }
    } catch (e) {
        console.warn("Sungas: could not load approver_roles from policy, using defaults", e);
    }
    _approver_roles_cache = APPROVER_ROLES_DEFAULT;
    return APPROVER_ROLES_DEFAULT;
}

frappe.ui.form.on("POS Closing Shift", {
    refresh: async function (frm) {
        const roles = await get_approver_roles(frm);

        // Restrict variance_approved_by to users holding an approver role.
        frm.set_query("variance_approved_by", function () {
            return {
                query: "frappe.core.doctype.user.user.user_query",
                filters: {
                    enabled: 1,
                    user_type: "System User",
                    role: ["in", roles],
                },
            };
        });

        // Draft + has variance => show banner
        if (frm.doc.docstatus === 0) {
            const variance = (frm.doc.payment_reconciliation || []).reduce(
                (acc, row) =>
                    acc + (flt(row.closing_amount) - flt(row.expected_amount)),
                0
            );
            if (Math.abs(variance) >= 1) {
                const sign = variance < 0 ? "shortage" : "overage";
                const msg = __(
                    `This shift has a NGN {0} ${sign}. ` +
                        `If it exceeds the block threshold, set <b>Variance Approved By</b> to ` +
                        `an approver (only users with the right role appear in the list), ` +
                        `fill <b>Variance Remarks</b>, then save. The cashier re-submits once approved.`,
                    [format_number(Math.abs(variance), null, 2)]
                );
                frm.dashboard.set_headline_alert(msg, "orange");
            }
        }
    },
});
