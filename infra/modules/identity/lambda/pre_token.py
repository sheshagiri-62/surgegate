"""Cognito pre-token-generation trigger (V2): put the organiser's tenant into the ACCESS token.

The booking API authorizes with access tokens. By default only ID tokens carry custom
attributes, so this trigger copies custom:tenant_id into a "tenant_id" claim on both tokens.
Groups (cognito:groups) are already in the access token. custom:tenant_id is set only by an
administrator (app clients cannot write it), so a user can never choose their own tenant.
"""


def handler(event, context):
    tenant_id = event["request"]["userAttributes"].get("custom:tenant_id")
    claims = {"tenant_id": tenant_id} if tenant_id else {}
    event["response"] = {
        "claimsAndScopeOverrideDetails": {
            "accessTokenGeneration": {"claimsToAddOrOverride": claims},
            "idTokenGeneration": {"claimsToAddOrOverride": claims},
        }
    }
    return event
