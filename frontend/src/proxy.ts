import { NextResponse } from "next/server";

// DEBUG MODE: middleware is disabled. All routes pass through unconditionally.
// Auth is handled client-side only. Re-enable after confirming UI loads.
export default function middleware() {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next|_clerk|v1|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
