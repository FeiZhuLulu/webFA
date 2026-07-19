import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "WebFA Control Center",
  description: "WebFA Runtime monitoring, identity management, and human control"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
