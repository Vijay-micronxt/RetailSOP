import hashlib
import secrets

import frappe


def generate_opaque_token():
	"""A refresh token is never a JWT - just a high-entropy random string.
	Only its hash is ever persisted (see hash_token); the raw value returned
	here is handed to the client once and never stored server-side.
	"""
	return secrets.token_urlsafe(48)


def hash_token(token):
	return hashlib.sha256(token.encode()).hexdigest()


def build_user_profile(user):
	"""Same shape returned by both login() and me() so a client's silent
	session-restore on app boot gets an identical object to what it got at
	login time.
	"""
	user_doc = frappe.get_cached_doc("User", user)
	return {
		"user": user_doc.name,
		"email": user_doc.email,
		"full_name": user_doc.full_name,
		"roles": frappe.get_roles(user),
	}
