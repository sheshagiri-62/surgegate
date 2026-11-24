// Password sign-in against Cognito (organiser-web is a public client: no secret), done on the
// server so the token goes straight into the httpOnly cookie.
import { NextResponse } from "next/server";

import { COOKIE, cookieOptions } from "@/lib/session";

export async function POST(req: Request) {
  const form = await req.formData();
  const region = process.env.COGNITO_REGION ?? "ap-south-1";
  const r = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
    },
    body: JSON.stringify({
      AuthFlow: "USER_AUTH",
      ClientId: process.env.COGNITO_CLIENT_ID,
      AuthParameters: {
        USERNAME: String(form.get("email") ?? ""),
        PASSWORD: String(form.get("password") ?? ""),
        PREFERRED_CHALLENGE: "PASSWORD",
      },
    }),
  });
  const data = await r.json();
  const result = data.AuthenticationResult;
  const base = new URL("/organiser/", req.url);
  if (!r.ok || !result) {
    const msg = encodeURIComponent(data.message ?? "Sign-in failed");
    return NextResponse.redirect(new URL(`login?error=${msg}`, base), 303);
  }
  const res = NextResponse.redirect(new URL("events", base), 303);
  res.cookies.set(COOKIE, result.AccessToken, cookieOptions(result.ExpiresIn));
  return res;
}
