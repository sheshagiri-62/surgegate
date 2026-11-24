import { NextResponse } from "next/server";

import { COOKIE, cookieOptions } from "@/lib/session";

export async function POST(req: Request) {
  const res = NextResponse.redirect(new URL("/organiser/login", req.url), 303);
  res.cookies.set(COOKIE, "", cookieOptions(0));
  return res;
}
