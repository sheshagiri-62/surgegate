// Password sign-in against Cognito (organiser-web is a public client: no secret), done on the
// server so the token goes straight into the httpOnly cookie.
import { seeOther } from "@/lib/redirect";
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
  if (!r.ok || !result) {
    return seeOther("/organiser/login", { error: data.message ?? "Sign-in failed" });
  }
  const res = seeOther("/organiser/events");
  const o = cookieOptions(result.ExpiresIn);
  res.headers.append(
    "Set-Cookie",
    `${COOKIE}=${result.AccessToken}; Path=${o.path}; Max-Age=${o.maxAge}; HttpOnly; SameSite=Strict${o.secure ? "; Secure" : ""}`,
  );
  return res;
}
