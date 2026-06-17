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

1. 用户在 Console 输入 token
2. 调用 `POST /v1/providers/github/connect`
3. token 存入 credential store
4. credential_ref 存入 provider_connections
5. 调用 GitHub API 测试连接
6. 更新 provider_connections.status

读取时:
1. GitHub adapter 内部调用 credential_store.get(credential_ref)
2. token 只在 adapter 内存中短暂存在
3. adapter 调用 GitHub API
4. token 不返回给调用方

断开时:
1. 调用 `DELETE /v1/providers/github/disconnect`
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
