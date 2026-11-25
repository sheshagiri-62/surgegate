import { seeOther } from "@/lib/redirect";
import { COOKIE } from "@/lib/session";

export async function POST() {
  const res = seeOther("/organiser/login");
  res.headers.append("Set-Cookie", `${COOKIE}=; Path=/organiser; Max-Age=0; HttpOnly; SameSite=Strict`);
  return res;
}
