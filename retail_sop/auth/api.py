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

Forgot/reset password (forgot_password/check_reset_token/reset_password)
follows the same "never touch Frappe's own Desk flow" philosophy: it
issues and validates its own opaque, hash-only-stored tokens (Password
Reset Request doctype, same pattern as the refresh token above) and emails
a link to this app's own frontend route, not frappe.core's
/update-password page.
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime
from frappe.utils.password import check_password

from retail_sop.auth.jwt_utils import encode_access_token, refresh_token_ttl_days
from retail_sop.auth.utils import build_user_profile, generate_opaque_token, hash_token

# How long a password reset link stays valid for.
PASSWORD_RESET_TTL_MINUTES = 60

# Where reset-link emails point - this app's own frontend, never Frappe's
# default /update-password page (see forgot_password() below).
CONF_FRONTEND_URL = "retail_sop_frontend_url"

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
	# See the matching comment in reset_password() - a filter-dict
	# frappe.db.set_value() call mishandles a datetime value on this
	# Frappe version, so this fetches matching names first and updates
	# each individually instead.
	session_names = frappe.get_all(
		"Auth Session",
		filters={"user": frappe.session.user, "revoked_at": ["is", "not set"]},
		pluck="name",
	)
	for session_name in session_names:
		frappe.db.set_value("Auth Session", session_name, "revoked_at", now_datetime())
	return {"success": True}


@frappe.whitelist()
def me():
	"""Same user-profile shape login() returns, for a silent session
	restore on app boot. Requires an authenticated request.
	"""
	return build_user_profile(frappe.session.user)


def _get_frontend_url():
	url = frappe.conf.get(CONF_FRONTEND_URL)
	if not url:
		frappe.throw(
			f"The frontend's URL is not configured. Set `{CONF_FRONTEND_URL}` in "
			"site_config.json so password reset emails link back to the app "
			"instead of failing to build a link at all."
		)
	return url.rstrip("/")


def _find_user_by_email(email):
	if not email:
		return None
	email = email.strip()
	# User.name usually *is* the email, but isn't guaranteed to be - fall
	# back to a lookup on the `email` field for accounts named differently.
	if frappe.db.exists("User", email):
		return email
	return frappe.db.get_value("User", {"email": email}, "name")


def _resolve_reset_request(email, token):
	"""Returns the still-valid, unused Password Reset Request doc matching
	this email+token pair, or None. Read-only - does not consume the token.
	"""
	user = _find_user_by_email(email)
	if not (user and token):
		return None

	request_name = frappe.db.get_value(
		"Password Reset Request",
		{"user": user, "token_hash": hash_token(token), "used_at": ["is", "not set"]},
		"name",
	)
	if not request_name:
		return None

	request = frappe.get_doc("Password Reset Request", request_name)
	if now_datetime() > get_datetime(request.expires_at):
		return None

	return request


@frappe.whitelist(allow_guest=True, methods=["POST"])
def forgot_password(email):
	"""Always returns {"success": True}, whether or not an account exists
	for `email` - an unauthenticated caller must never be able to tell
	account existence apart from a miss (that's also why any failure below
	is swallowed rather than surfaced as an error response).

	If `email` matches an enabled, app-permitted account, emails it a link
	to *this app's own* /reset-password page (retail_sop_frontend_url),
	never Frappe's default /update-password page - the whole point of this
	endpoint over frappe.core's built-in reset_password().
	"""
	try:
		_try_send_reset_email(email)
	except Exception:
		# Same fail-safe philosophy as auth/middleware.py: a bug or a
		# missing site_config key here must never leak account existence
		# (a 500 here vs the normal 200 would do exactly that) or crash the
		# request - log it, return success either way.
		frappe.log_error(title="retail_sop: forgot_password error")

	return {"success": True}


def _try_send_reset_email(email):
	user = _find_user_by_email(email)
	if not user:
		return

	user_doc = frappe.get_cached_doc("User", user)
	if not user_doc.enabled:
		return
	if not set(frappe.get_roles(user)) & ALLOWED_ROLES:
		return

	# Already have a live, unused link from the last minute - don't spam a
	# fresh email (and token) on every double-click/retry.
	recent = frappe.db.get_value(
		"Password Reset Request",
		{
			"user": user,
			"used_at": ["is", "not set"],
			"created_at": [">", add_to_date(now_datetime(), seconds=-60)],
		},
		"name",
	)
	if recent:
		return

	# Only the newest link should ever work.
	frappe.db.set_value(
		"Password Reset Request",
		{"user": user, "used_at": ["is", "not set"]},
		"expires_at",
		now_datetime(),
	)

	raw_token = generate_opaque_token()
	request = frappe.new_doc("Password Reset Request")
	request.user = user
	request.token_hash = hash_token(raw_token)
	request.created_at = now_datetime()
	request.expires_at = add_to_date(now_datetime(), minutes=PASSWORD_RESET_TTL_MINUTES)
	request.insert(ignore_permissions=True)

	reset_link = (
		f"{_get_frontend_url()}/reset-password"
		f"?token={quote(raw_token)}&email={quote(user_doc.email or user)}"
	)

	message = (
		f"Hi {user_doc.full_name or user},<br><br>"
		"Someone requested a password reset for your Retail SOP account. "
		"If this was you, click the link below to set a new password "
		f"(valid for {PASSWORD_RESET_TTL_MINUTES} minutes):<br><br>"
		f'<a href="{reset_link}">{reset_link}</a><br><br>'
		"If you didn't request this, you can safely ignore this email - "
		"your password hasn't changed."
	)

	frappe.sendmail(
		recipients=[user_doc.email or user],
		subject=_("Reset your Retail SOP password"),
		message=message,
		now=True,
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def check_reset_token(email, token):
	"""Read-only pre-check so the frontend can show "this link is invalid
	or has expired" immediately on page load, before the user fills in a
	new password - rather than only discovering that on submit.
	"""
	return {"valid": bool(_resolve_reset_request(email, token))}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def reset_password(email, token, new_password):
	if not (email and token and new_password):
		frappe.throw(_("email, token and new_password are all required."))

	request = _resolve_reset_request(email, token)
	if not request:
		frappe.throw(_("This reset link is invalid or has expired."), frappe.AuthenticationError)

	user = request.user

	# .new_password is Frappe's own mechanism (same one Desk's "Set New
	# Password" and the default reset-password page use) - it re-runs the
	# site's password policy and handles hashing; reset_password() doesn't
	# reinvent either.
	user_doc = frappe.get_doc("User", user)
	user_doc.new_password = new_password
	user_doc.save(ignore_permissions=True)

	request.used_at = now_datetime()
	request.save(ignore_permissions=True)

	# Password just changed - force re-login everywhere, same as logout_all().
	# frappe.db.set_value() with a filter dict (rather than a single
	# docname) mishandles a datetime value on this Frappe version - it
	# reaches MariaDB as an empty string instead, which the column rejects
	# (OperationalError 1292). Fetching the matching names first and
	# updating each individually uses the same single-docname form already
	# proven reliable elsewhere in this file (see refresh_token() above).
	session_names = frappe.get_all(
		"Auth Session", filters={"user": user, "revoked_at": ["is", "not set"]}, pluck="name"
	)
	for session_name in session_names:
		frappe.db.set_value("Auth Session", session_name, "revoked_at", now_datetime())

	return {"success": True}
