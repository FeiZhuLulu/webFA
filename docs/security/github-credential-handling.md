# Legacy: GitHub Credential Handling

This document is historical transaction/provider guidance. It is not part of
the current default WebFA agent-browser path.

Current WebFA developer preview does not expose GitHub PAT collection or
GitHub-specific business tools through the default MCP surface. Default MCP
tools remain only the five browser tools.

# GitHub 凭证处理规范

## 认证方式

v0 使用 fine-grained personal access token (PAT)。
v1 再考虑 GitHub App。

## 推荐 token 权限 (P3 只读)

```
Repository access: Only selected repositories
Repository permissions:
  - Metadata: read
  - Contents: read
  - Issues: read
  - Pull requests: read (可选)
```

P4 需要额外:
```
  - Contents: read/write (创建文件)
  - Pull requests: read/write (创建 PR)
```

## 存储方式

### Credential Store

文件: `packages/storage/credential_store.py`

存储路径:
- Windows: `%APPDATA%/WebFA/credentials/github/default.json`
- macOS: `~/Library/Application Support/WebFA/credentials/github/default.json`
- Linux: `~/.config/webfa/credentials/github/default.json`

存储格式:
```json
{
  "credential_ref": "github:default",
  "token": "github_pat_..."
}
```

这是历史 Provider 路径的本地文件存储，不是硬件 Vault，也不承诺在本机用户账户已经
失陷后保护 PAT。文件内容仍是明文 token；安全边界依赖 WebFA 数据目录所属的本地操作
系统账户。POSIX 上 credentials 目录和文件分别收紧为 `0700`/`0600`；Windows 上继承
用户数据目录的 ACL。不要把 `WEBFA_HOME` 指向共享目录。

Credential ref 的 provider/connection 两段都经过严格校验，读取不会创建目录，符号链接
逃逸会被拒绝。写入使用同目录私有临时文件、flush/fsync 和原子 replace；替换失败时保留
上一份完整凭据并清理临时文件。该机制保证边界与崩溃一致性，不等同于静态加密。

### provider_connections 表

只保存引用，不保存 token:
```
credential_ref = github:default
auth_mode = fine_grained_pat
status = connected
```

禁止:
- SQLite 中保存 raw token
- audit_events 中出现 token
- resource_snapshots 中出现 token
- proofs 中出现 token

## Token 红线

### 必须 redaction 的 pattern

```
github_pat_***
ghp_***
gho_***
ghu_***
ghs_***
ghr_***
Bearer ***
Authorization: ***
```

### Redaction 位置

- 日志 (logs/)
- 审计 (audit_events)
- 错误响应
- 证明 (proofs)
- 快照 (resource_snapshots)
- MCP 响应
- Console UI (不回显)
- Electron 日志

### 允许出现

```
token_redacted
redacted=true
credential_ref
auth_mode
token_stored=true
```

## 凭证生命周期

Provider connection 的 status/connect/test/disconnect 全部属于本地人类控制面，而不是
Agent Runtime API。调用方必须配置 `WEBFA_VISUALIZER_CONTROL_TOKEN`，并在每次请求中发送
`X-WebFA-Visualizer-Token`；缺少配置时 Runtime fail closed，缺少或错误 header 时拒绝请求。
该控制 Token 不得进入 MCP 配置、Agent prompt、URL、响应或持久化的 Provider 记录。

1. 用户在受信任的本地控制面输入 token
2. 带控制 header 调用 `POST /v1/providers/github/connect`
3. token 存入 credential store
4. credential_ref 存入 provider_connections
5. 调用 GitHub API 测试连接
6. 更新 provider_connections.status

凭据文件替换与 SQLite 元数据提交由同一进程内生命周期锁串行化。如果元数据事务失败，
connect 会恢复先前凭据（或删除新凭据）；disconnect 会恢复刚删除的凭据。数据库按
`provider` 自然键读取连接记录，不能把随机记录 `id` 当作 provider 名。

读取时:
1. GitHub adapter 内部调用 credential_store.get(credential_ref)
2. token 只在 adapter 内存中短暂存在
3. adapter 调用 GitHub API
4. token 不返回给调用方

断开时:
1. 带控制 header 调用 `DELETE /v1/providers/github/disconnect`
2. credential store 删除 token 文件
3. provider_connections.status = disconnected
4. credential_ref = null

## MCP 安全

MCP 不新增:
- webfa.github.connect
- webfa.github.save_token
- webfa.github.get_token
- webfa.github.read_file

MCP 只能通过:
- webfa.discover (显示 GitHub connected/read_only)
- webfa.plan (创建 plan-only)
- webfa.preview (plan-only preview)
- webfa.execute (GitHub 被阻断)
