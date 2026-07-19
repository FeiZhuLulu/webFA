import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "WebFA 会话监控",
  description: "WebFA Browser Session 的本地只读监控与临时人工接管界面。",
};

export default function MonitorLayout({ children }: { children: ReactNode }) {
  return children;
}
