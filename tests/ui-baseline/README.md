# UI 视觉回归 Baseline

此目录存放 `npm run audit:source:ui` 的 12 张 baseline 截图，与审计 capture 一一对应。

- 正常审计会把每次 capture 与此处的 baseline 逐像素比较（通道差 ≤16 视为同像素，总差异率阈值默认 0.2%，可用 `WEBFA_UI_AUDIT_DIFF_TOLERANCE` 调整），超阈即失败，并在审计输出目录生成 `diff-*.png` 热图供人工审查。
- 有意的 UI 视觉变更通过后，运行 `npm run audit:source:ui:update` 刷新 baseline。
- baseline 在本机（Windows + Segoe UI Variable 字体栈）生成。跨平台或字体栈不同的环境可能出现渲染差异，请先人工核对 diff 热图再决定是否刷新 baseline，不要直接把跨机差异刷进 baseline。
