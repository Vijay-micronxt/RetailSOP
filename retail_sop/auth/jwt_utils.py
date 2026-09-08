"""Stateless JWT access tokens, HS256, with rotatable signing keys.

Signing keys live in site_config.json, not hardcoded, so they can be
rotated without a deploy:

    "retail_sop_jwt_keys": {
        "2026-01": "<random secret>",
        "2026-02": "<random secret>"
    },
    "retail_sop_jwt_active_kid": "2026-02"

Only `retail_sop_jwt_active_kid` signs new tokens. To rotate: add a new
kid/secret pair, point `retail_sop_jwt_active_kid` at it, and keep the old
kid's secret in `retail_sop_jwt_keys` until every token signed with it has
expired (access_token_ttl() after the switch), then remove it.

Optional tuning (also in site_config.json, both have sane defaults so
these can be omitted):

    "retail_sop_access_token_ttl_seconds": 2400,   # 40 minutes
    "retail_sop_refresh_token_ttl_days": 30
"""

import time

import frappe
import jwt

ALGORITHM = "HS256"

CONF_KEYS = "retail_sop_jwt_keys"
CONF_ACTIVE_KID = "retail_sop_jwt_active_kid"
CONF_ACCESS_TTL = "retail_sop_access_token_ttl_seconds"
CONF_REFRESH_TTL_DAYS = "retail_sop_refresh_token_ttl_days"

DEFAULT_ACCESS_TTL_SECONDS = 40 * 60
DEFAULT_REFRESH_TTL_DAYS = 30


def _get_keys():
	keys = frappe.conf.get(CONF_KEYS)
	if not keys:
		frappe.throw(
			f"JWT signing keys are not configured. Set `{CONF_KEYS}` (a {{kid: secret}} map) "
			"in site_config.json."
		)
	return keys


def _get_active_kid():
	kid = frappe.conf.get(CONF_ACTIVE_KID)
	if not kid:
		frappe.throw(f"No active JWT signing key configured. Set `{CONF_ACTIVE_KID}` in site_config.json.")
	return kid


def access_token_ttl():
	"""Seconds."""
	return int(frappe.conf.get(CONF_ACCESS_TTL) or DEFAULT_ACCESS_TTL_SECONDS)


def refresh_token_ttl_days():
	return int(frappe.conf.get(CONF_REFRESH_TTL_DAYS) or DEFAULT_REFRESH_TTL_DAYS)


def encode_access_token(user, session_name):
	"""Returns (token, ttl_seconds)."""
	keys = _get_keys()
	active_kid = _get_active_kid()
	secret = keys.get(active_kid)
	if not secret:
		frappe.throw(f"Active JWT kid '{active_kid}' has no secret in `{CONF_KEYS}`.")

	ttl = access_token_ttl()
	now = int(time.time())
	payload = {
		"sub": user,
		"sid": session_name,
		"type": "access",
		"iat": now,
		"exp": now + ttl,
	}
	token = jwt.encode(payload, secret, algorithm=ALGORITHM, headers={"kid": active_kid})
	return token, ttl


def decode_access_token(token):
	"""Verifies signature + expiry + token type. Returns the payload dict.

	Raises a jwt.PyJWTError subclass (InvalidTokenError, ExpiredSignatureError,
	DecodeError, ...) on any failure - callers should catch `jwt.PyJWTError`
	broadly rather than enumerate every subclass.
	"""
	keys = _get_keys()

	header = jwt.get_unverified_header(token)
	kid = header.get("kid")
	if not kid or kid not in keys:
		raise jwt.InvalidTokenError("Unknown signing key")

	payload = jwt.decode(token, keys[kid], algorithms=[ALGORITHM])
	if payload.get("type") != "access":
		raise jwt.InvalidTokenError("Not an access token")

	return payload
