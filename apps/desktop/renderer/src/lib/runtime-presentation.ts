import type { RuntimeIssue, RuntimeStatus } from "../types/webfa-desktop";

export type RuntimeIssuePresentation = {
  eyebrow: string;
  title: string;
  detail: string;
  actionLabel: string;
  tone: "warning" | "error";
};

const ISSUE_PRESENTATIONS: Record<RuntimeIssue["code"], RuntimeIssuePresentation> = {
  external_runtime: {
    eyebrow: "OWNERSHIP",
    title: "端点已有 WebFA Runtime",
    detail: "Desktop 没有接管外部进程，也没有取得控制令牌。请先停止该 Runtime，或为 Desktop 配置其他本地端口。",
    actionLabel: "重新检测并启动",
    tone: "warning",
  },
  endpoint_collision: {
    eyebrow: "LOCAL ENDPOINT",
    title: "Runtime 端口被其他服务占用",
    detail: "WebFA 已拒绝附加到身份不匹配的本地服务。释放该端口或调整 Desktop 端口后再重试。",
    actionLabel: "重新检测并启动",
    tone: "error",
  },
  ownership_changed: {
    eyebrow: "OWNERSHIP",
    title: "启动期间端点归属发生变化",
    detail: "Desktop 已停止自己的启动进程，并拒绝向未知服务发放控制权限。请检查端口占用后重试。",
    actionLabel: "重新检测并启动",
    tone: "error",
  },
  spawn_failed: {
    eyebrow: "PROCESS",
    title: "无法启动 Runtime 进程",
    detail: "Desktop 没有获得可验证的 Runtime。请查看本地应用日志确认 sidecar 或系统环境问题，然后重试。",
    actionLabel: "重试启动",
    tone: "error",
  },
  startup_timeout: {
    eyebrow: "HEALTH CHECK",
    title: "Runtime 启动超时",
    detail: "进程没有在限定时间内提供匹配版本与实例身份的健康响应。WebFA 已清理自己的启动进程。",
    actionLabel: "重试启动",
    tone: "error",
  },
  startup_failed: {
    eyebrow: "STARTUP",
    title: "Runtime 启动失败",
    detail: "Runtime 报告了启动故障。详细诊断只保留在本地应用日志中，界面不会展示原始堆栈或路径。",
    actionLabel: "重试启动",
    tone: "error",
  },
  runtime_exited: {
    eyebrow: "PROCESS",
    title: "Runtime 意外退出",
    detail: "Desktop 已撤销本次 Runtime 的控制令牌并停止展示旧状态。确认本地环境后可以重新启动。",
    actionLabel: "重新启动",
    tone: "error",
  },
  cleanup_failed: {
    eyebrow: "PROCESS OWNERSHIP",
    title: "Runtime 尚未安全停止",
    detail: "Desktop 无法确认自己持有的进程树已经退出，因此继续保留所有权。请再次停止，切勿直接附加其他 Runtime。",
    actionLabel: "再次停止",
    tone: "error",
  },
};

export function presentRuntimeIssue(status: RuntimeStatus | null): RuntimeIssuePresentation | null {
  if (status?.issue) return ISSUE_PRESENTATIONS[status.issue.code];
  if (status?.ownership === "external") return ISSUE_PRESENTATIONS.external_runtime;
  if (status?.ownership === "collision") return ISSUE_PRESENTATIONS.endpoint_collision;
  return null;
}
