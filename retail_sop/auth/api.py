"""Stateless JWT bearer-token auth, replacing Frappe's cookie-session
login entirely for API-driven clients (SPA/mobile). See auth/middleware.py
for the `before_request` bypass that makes an already-issued access token
authenticate a request, and auth/jwt_utils.py for the token mechanics.

Two token types:
  - access_token: short-lived JWT (see jwt_utils.access_token_ttl()),
    verified stateless on every request - no DB read needed to check the
    signature/expiry - but still checked against Auth Session.revoked_at
    so logout takes effect immediately.
  - refresh_token: an opaque random string, never a JWT. Only its sha256
    hash is ever persisted; the raw value is returned to the client once
    and never stored server-side.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime
from frappe.utils.password import check_password

from retail_sop.auth.jwt_utils import encode_access_token, refresh_token_ttl_days
from retail_sop.auth.utils import build_user_profile, generate_opaque_token, hash_token

# This app's own "is this account allowed to use this app" gate - the
# staff roles that may hold an Auth Session, plus System Manager as an
# admin escape hatch. Store Operator is intentionally read-only at the API
# level (see retail_sop.api.get_my_store_summary) - being allowed to log
# in here doesn't grant it access to the broader supervisor/manager
# endpoints, which require doctype read permissions Store Operator doesn't
# have.
ALLOWED_ROLES = {"Food Court Supervisor", "Food Court Manager", "Store Operator", "System Manager"}


def _ensure_allowed(user):
	user_doc = frappe.get_cached_doc("User", user)
	if not user_doc.enabled:
		frappe.throw(_("This account is disabled."), frappe.AuthenticationError)

	if not set(frappe.get_roles(user)) & ALLOWED_ROLES:
		frappe.throw(_("This account is not permitted to use this app."), frappe.PermissionError)


def _issue_session(user, device_id, device_name=None):
	refresh_token = generate_opaque_token()

	session = frappe.new_doc("Auth Session")
	session.user = user
	session.device_id = device_id
	session.device_name = device_name
	session.issued_at = now_datetime()
	session.expires_at = add_to_date(now_datetime(), days=refresh_token_ttl_days())
	session.refresh_token_hash = hash_token(refresh_token)
	session.insert(ignore_permissions=True)

	access_token, ttl = encode_access_token(user, session.name)

	return {
		"access_token": access_token,
		"refresh_token": refresh_token,
		"token_type": "Bearer",
		"expires_in": ttl,
		"user": build_user_profile(user),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def login(usr, pwd, device_id, device_name=None):
	if not (usr and pwd and device_id):
		frappe.throw(_("usr, pwd and device_id are required."))

	# Never roll your own password check - this is Frappe's own verifier,
	# and it already raises frappe.AuthenticationError on a bad password.
	check_password(usr, pwd)

	_ensure_allowed(usr)

	return _issue_session(usr, device_id, device_name)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def forgot_password(usr):
	"""Triggers Frappe's own built-in password-reset email flow - same
	"never roll your own" reasoning as login()'s use of check_password().
	Reuses frappe.core.doctype.user.user.reset_password(), which generates
	a one-time key on the User record and emails a reset link the
	frontend doesn't need to build any part of.

	Completing the reset is Frappe's own existing endpoint too, called
	directly by the frontend - no wrapper needed here:
	frappe.core.doctype.user.user.update_password(new_password, key=<key
	from the emailed link>). Once that succeeds, the account's password
	is updated and login() works immediately with the new password - both
	check the same underlying password hash.

	Always returns {"success": True} regardless of whether the account
	exists, is enabled, or is allowed to use this app - so this can't be
	used to discover valid usernames/emails on this (shared, multi-app)
	site.
	"""
	if not usr:
		frappe.throw(_("usr is required."))

	if frappe.db.exists("User", usr):
		user_doc = frappe.get_cached_doc("User", usr)
		if user_doc.enabled and set(frappe.get_roles(usr)) & ALLOWED_ROLES:
			from frappe.core.doctype.user.user import reset_password

			reset_password(user=usr)

	return {"success": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def refresh_token(refresh_token):
	if not refresh_token:
		frappe.throw(_("refresh_token is required."))

	presented_hash = hash_token(refresh_token)

	session_name = frappe.db.get_value(
		"Auth Session",
		{"refresh_token_hash": presented_hash, "revoked_at": ["is", "not set"]},
		"name",
	)

	if not session_name:
		# Not a live token - but is it a token that was already rotated out
		# once? Presenting a stale refresh token again means it was either
		# lost/leaked and someone else already used it, or a client bug
		# replayed an old value. Either way, treat it as theft: kill the
		# session outright rather than silently rejecting just this call.
		reused_session_name = frappe.db.get_value(
			"Auth Session",
			{"prev_refresh_token_hash": presented_hash, "revoked_at": ["is", "not set"]},
			"name",
		)
		if reused_session_name:
			frappe.db.set_value("Auth Session", reused_session_name, "revoked_at", now_datetime())
			frappe.throw(
				_("This refresh token has already been used. The session has been revoked."),
				frappe.AuthenticationError,
			)

		frappe.throw(_("Invalid or expired refresh token."), frappe.AuthenticationError)

	session = frappe.get_doc("Auth Session", session_name)

	if session.expires_at and now_datetime() > get_datetime(session.expires_at):
		frappe.throw(_("Refresh token has expired."), frappe.AuthenticationError)

	new_refresh_token = generate_opaque_token()
	session.prev_refresh_token_hash = session.refresh_token_hash
	session.refresh_token_hash = hash_token(new_refresh_token)
	session.expires_at = add_to_date(now_datetime(), days=refresh_token_ttl_days())

	try:
		session.save(ignore_permissions=True)
	except frappe.TimestampMismatchError:
		# Two concurrent refresh calls raced on the same session - the
		# other one already won and rotated the token. This is not theft,
		# just a lost race; the client should retry with whichever token
		# it has (the winner's response, if it got one).
		frappe.throw(
			_("This refresh token was already used by a concurrent request. Please retry."),
			frappe.ValidationError,
		)

	access_token, ttl = encode_access_token(session.user, session.name)

	return {
		"access_token": access_token,
		"refresh_token": new_refresh_token,
		"token_type": "Bearer",
		"expires_in": ttl,
		"user": build_user_profile(session.user),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def logout(refresh_token):
	# Always return success either way - never leak whether the token was
	# recognized.
	if refresh_token:
		presented_hash = hash_token(refresh_token)
		session_name = frappe.db.get_value(
			"Auth Session",
			{"refresh_token_hash": presented_hash, "revoked_at": ["is", "not set"]},
			"name",
		)
		if session_name:
			frappe.db.set_value("Auth Session", session_name, "revoked_at", now_datetime())

	return {"success": True}


@frappe.whitelist()
def logout_all():
	"""Requires an authenticated request (a valid Authorization header
	already processed by the before_request hook) - not allow_guest.
	"""
	frappe.db.set_value(
		"Auth Session",
		{"user": frappe.session.user, "revoked_at": ["is", "not set"]},
		"revoked_at",
		now_datetime(),
	)
	return {"success": True}


@frappe.whitelist()
def me():
	"""Same user-profile shape login() returns, for a silent session
	restore on app boot. Requires an authenticated request.
	"""
	return build_user_profile(frappe.session.user)
