"""The bearer-token bypass of Frappe's cookie/CSRF session machinery.

Registered as a `before_request` hook (see hooks.py). If the request
carries a valid `Authorization: Bearer <access_token>`, this makes the
rest of the request run as that real Frappe user (roles evaluated live,
normally, by everything downstream) - no `sid` cookie involved, so
Frappe's CSRF check (which only triggers for cookie-backed sessions)
never engages either. That is what "bypassing the regular flow" means
here: routing around the cookie/CSRF machinery in favor of the bearer
token, not disabling any security check.

If there's no/garbage/expired Authorization header, this does nothing -
the request proceeds as Guest, and any protected endpoint's own
`frappe.whitelist(allow_guest=False)` (the default) rejects it with a
normal PermissionError. Whitelisted login/refresh/logout endpoints are
`allow_guest=True` and don't need this hook to have run at all.
"""

import frappe
import jwt as pyjwt

from retail_sop.auth.jwt_utils import decode_access_token


def authenticate_request():
	try:
		_authenticate_request()
	except Exception:
		# This hook runs on every single request, Guest and authenticated
		# alike. A bug or a misconfigured site_config here must never take
		# the whole site down - worst case, fail safe: the request proceeds
		# as Guest and gets a normal PermissionError from whitelist() on any
		# protected endpoint.
		frappe.log_error(title="retail_sop: JWT auth middleware error")


def _authenticate_request():
	auth_header = frappe.get_request_header("Authorization")
	if not auth_header:
		return

	scheme, _, token = auth_header.partition(" ")
	if scheme.lower() != "bearer" or not token.strip():
		return

	try:
		payload = decode_access_token(token.strip())
	except pyjwt.PyJWTError:
		return

	user = payload.get("sub")
	session_name = payload.get("sid")
	if not user or not session_name:
		return

	# The one DB read per request: re-checks the session hasn't been
	# revoked, which is what makes logout take effect immediately instead
	# of waiting for the JWT to expire on its own.
	session = frappe.db.get_value("Auth Session", session_name, "revoked_at", as_dict=True)
	if not session or session.revoked_at:
		return

	# frappe.set_user() resets frappe.local.form_dict as a side effect (it
	# assumes it's called before the request body is parsed). This hook
	# runs after parsing, so save/restore form_dict around the call or the
	# request's params silently vanish.
	saved_form_dict = frappe.local.form_dict
	frappe.set_user(user)
	frappe.local.form_dict = saved_form_dict
