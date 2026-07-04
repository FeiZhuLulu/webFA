import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "WebFA Visualizer",
  description: "WebFA Runtime Inspector and Human Takeover Panel"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
