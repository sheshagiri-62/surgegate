"""Cognito pre-token-generation trigger (V2): put the organiser's tenant into the ACCESS token.

The booking API authorizes with access tokens. By default only ID tokens carry custom
attributes, so this trigger copies custom:tenant_id into a "tenant_id" claim on both tokens,
and the verified email into an "email" claim (Day 8 Task 4: stored on the order).
Groups (cognito:groups) are already in the access token. custom:tenant_id is set only by an
administrator (app clients cannot write it), so a user can never choose their own tenant.
"""


def handler(event, context):
    attrs = event["request"]["userAttributes"]
    claims = {}
    if tenant_id := attrs.get("custom:tenant_id"):
        claims["tenant_id"] = tenant_id
    # The buyer's email, so an order can store it at creation (ticket email, attendee export)
    # without a Cognito lookup per row. Only a verified address is copied.
    if attrs.get("email") and attrs.get("email_verified") in ("true", True):
        claims["email"] = attrs["email"]
    event["response"] = {
        "claimsAndScopeOverrideDetails": {
            "accessTokenGeneration": {"claimsToAddOrOverride": claims},
            "idTokenGeneration": {"claimsToAddOrOverride": claims},
        }
    }
    return event
