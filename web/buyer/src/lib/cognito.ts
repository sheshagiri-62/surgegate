// Minimal Cognito sign-in straight from the browser (no SDK): the public Cognito API accepts
// JSON calls with an X-Amz-Target header and allows CORS. The buyer-web client is a public
// client (no secret), so nothing secret ships in this bundle.
//
// Flows (USER_AUTH, "choice-based"):
//   email + OTP : InitiateAuth(PREFERRED_CHALLENGE=EMAIL_OTP) -> code by email -> RespondToAuthChallenge
//   password    : InitiateAuth(PREFERRED_CHALLENGE=PASSWORD, PASSWORD) -> tokens (dev test users)

const REGION = process.env.NEXT_PUBLIC_COGNITO_REGION ?? "ap-south-1";
const CLIENT_ID = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "";
const ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;

export interface Tokens {
  accessToken: string;
  expiresAt: number; // epoch ms
}

interface AuthResponse {
  AuthenticationResult?: { AccessToken: string; ExpiresIn: number };
  ChallengeName?: string;
  Session?: string;
}

async function call<T>(target: string, body: object): Promise<T> {
  const r = await fetch(ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.message ?? data.__type ?? `Cognito error ${r.status}`);
  return data as T;
}

function tokens(res: AuthResponse): Tokens {
  const result = res.AuthenticationResult;
  if (!result) throw new Error(`unexpected challenge: ${res.ChallengeName ?? "none"}`);
  return { accessToken: result.AccessToken, expiresAt: Date.now() + result.ExpiresIn * 1000 };
}

/** Step 1 of email + OTP: Cognito emails a code; returns the session for step 2. */
export async function startEmailOtp(email: string): Promise<string> {
  const res = await call<AuthResponse>("InitiateAuth", {
    AuthFlow: "USER_AUTH",
    ClientId: CLIENT_ID,
    AuthParameters: { USERNAME: email, PREFERRED_CHALLENGE: "EMAIL_OTP" },
  });
  if (res.ChallengeName !== "EMAIL_OTP" || !res.Session) {
    throw new Error("email code sign-in is not available for this account");
  }
  return res.Session;
}

/** Step 2 of email + OTP. */
export async function finishEmailOtp(email: string, session: string, code: string): Promise<Tokens> {
  return tokens(
    await call<AuthResponse>("RespondToAuthChallenge", {
      ChallengeName: "EMAIL_OTP",
      ClientId: CLIENT_ID,
      Session: session,
      ChallengeResponses: { USERNAME: email, EMAIL_OTP_CODE: code },
    }),
  );
}

export async function signInWithPassword(email: string, password: string): Promise<Tokens> {
  return tokens(
    await call<AuthResponse>("InitiateAuth", {
      AuthFlow: "USER_AUTH",
      ClientId: CLIENT_ID,
      AuthParameters: { USERNAME: email, PREFERRED_CHALLENGE: "PASSWORD", PASSWORD: password },
    }),
  );
}

// The access token lives in sessionStorage: it survives a refresh of this tab but not closing it,
// and is never sent anywhere except the API. (Trade-off: readable by scripts on this origin;
// the page loads no third-party scripts.)
const KEY = "surgegate.tokens";

export function saveTokens(t: Tokens): void {
  sessionStorage.setItem(KEY, JSON.stringify(t));
}

export function loadTokens(): Tokens | null {
  try {
    const t = JSON.parse(sessionStorage.getItem(KEY) ?? "null") as Tokens | null;
    return t && t.expiresAt > Date.now() + 30_000 ? t : null;
  } catch {
    return null;
  }
}

export function signOut(): void {
  sessionStorage.removeItem(KEY);
}
