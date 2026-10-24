import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "CNU Insights", template: "%s · CNU Insights" },
  description: "CNU 서비스 인사이트 워크스페이스",
  robots: { index: false, follow: false },
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
