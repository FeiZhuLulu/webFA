import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "WebFA Desktop",
  description: "Local Agent Action Transaction Gateway console"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
