import { NextRequest, NextResponse } from "next/server";
import { authFailure } from "./lib/auth";

export function proxy(request: NextRequest) {
  return (
    authFailure(request.headers.get("authorization")) ?? NextResponse.next()
  );
}
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt).*)"],
};
