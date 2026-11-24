// The organiser's Cognito access token lives in an httpOnly, SameSite=Strict cookie scoped to
// /organiser: page JavaScript can't read it, and other sites can't make the browser send it.
import { cookies } from "next/headers";

export const COOKIE = "sg_org";

export async function token(): Promise<string | null> {
  return (await cookies()).get(COOKIE)?.value ?? null;
}

export const cookieOptions = (maxAge: number) => ({
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "strict" as const,
  path: "/organiser",
  maxAge,
});
