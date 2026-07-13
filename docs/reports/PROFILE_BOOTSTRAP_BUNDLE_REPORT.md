# WebFA Profile Bundle Export / Restore Report

Status: implemented and accepted

Date: 2026-07-13

## 1. Scope

This phase completes Post-Core Profile Bootstrap with an encrypted, integrity-checked transport format for persistent BrowserProfile identity.

Implemented:

```text
WebFA Profile Bundle export
WebFA Profile Bundle restore to a new Profile
native desktop streaming save/open
real Chromium identity roundtrip
```

The Bundle carries Chromium browser identity and website storage. It is therefore treated as a credential-bearing security asset rather than a normal settings archive.

The default Agent MCP surface remains exactly five tools. Bundle export and restore exist only on the protected local control plane.

## 2. Format

File extension:

```text
.webfa-profile
```

Media type:

```text
application/vnd.webfa.profile-bundle
```

Container layout:

```text
8 bytes   WEBFAPB1 magic
4 bytes   big-endian JSON header length
N bytes   canonical JSON encryption header
M bytes   AES-256-GCM ciphertext
16 bytes  GCM authentication tag
```

The plaintext is a ZIP64 archive using only `ZIP_STORED` members.

The plaintext archive contains:

```text
manifest.json
profile/<relative Chromium user-data file>
```

No browser identity metadata or Profile filename appears in the unencrypted header. The header contains only:

- format and version;
- fixed cipher and KDF identifiers;
- random salt;
- random nonce;
- plaintext byte count;
- creation timestamp.

## 3. Encryption

Key derivation:

```text
Scrypt
N = 32768
r = 8
p = 1
output = 32 bytes
salt = 16 random bytes
```

Encryption:

```text
AES-256-GCM
nonce = 12 random bytes
tag = 16 bytes
```

The magic, encoded header length, and canonical header bytes are authenticated as additional data.

Encryption and decryption are streaming operations. The complete Profile archive is never loaded into Python or Renderer memory.

The user passphrase must contain 12 to 1024 characters. The passphrase is never written into the Bundle, manifest, runtime event, API response, or UI log.

A wrong passphrase and a modified ciphertext return the same bounded error class:

```text
profile_bundle_passphrase_invalid
```

This avoids exposing whether failure came from the secret or the ciphertext.

## 4. Manifest Integrity

The encrypted manifest contains only the minimum restore metadata:

```text
format/version
creation time
source safe alias/display name/bootstrap source
file count
total byte count
excluded runtime-entry count
per-file relative path
per-file byte count
per-file SHA-256
```

Before encryption, WebFA reopens the generated archive and independently validates every manifest member and SHA-256 digest. This catches non-WebFA filesystem changes that occur while the source Profile is locked but before encryption completes.

Restore validates the archive twice:

1. after upload and authenticated decryption, before showing the preview;
2. after a second authenticated decryption, immediately before extraction.

The manifest digest must be identical across preview and commit.

## 5. Cold Export

Source requirements:

- persistent BrowserProfile;
- catalog state `ready`;
- exact Profile version;
- no active BrowserSession;
- no concurrent Profile maintenance operation.

Export flow:

```text
protected preview request
  -> source ProfileMutationLease
  -> storage snapshot and fingerprint
  -> redacted preview
  -> user supplies and confirms passphrase
  -> reacquire source ProfileMutationLease
  -> verify source fingerprint
  -> build and self-verify plaintext archive
  -> stream-encrypt Bundle
  -> stream response to Electron main process
  -> native save dialog and direct disk write
  -> delete Runtime artifact after response
```

If the source changes after preview, export returns:

```text
profile_bundle_source_changed
```

The preview is invalidated rather than silently exporting a different identity snapshot.

## 6. Streaming Desktop Boundary

The Electron Renderer does not use `response.blob()` in the normal desktop path.

Export:

```text
Runtime FileResponse
  -> Electron main-process fetch stream
  -> Node stream pipeline
  -> user-selected destination file
```

Restore:

```text
user-selected local Bundle
  -> Node read stream
  -> protected Runtime upload stream
  -> authenticated restore preview
```

The Renderer receives only:

- selected basename;
- byte counts;
- encrypted Bundle SHA-256;
- redacted preview metadata.

It never receives the full local path or Bundle bytes in the desktop path.

A browser-development fallback exists and may use a Blob for small local test Bundles. Production Electron uses the streaming bridge.

## 7. Restore Upload and Preview

The protected restore preview endpoint accepts an octet stream and writes it incrementally to a Runtime-owned temporary file.

Limits:

```text
maximum encrypted Bundle: 52 GiB
maximum plaintext archive: 50 GiB
maximum files:             200,000
maximum encryption header: 16 KiB
maximum manifest:          2 MiB
preview TTL:               10 minutes
pending restore previews:  10
```

The encrypted upload remains encrypted while the user reviews the preview. WebFA decrypts into a mode-0600 temporary ZIP only for bounded validation and immediately deletes that plaintext file.

The pending preview stores the encrypted upload and passphrase in Runtime memory. Both are deleted on:

- successful restore;
- explicit cancel;
- preview expiry;
- pending-preview eviction;
- Runtime shutdown.

## 8. Archive Safety

WebFA never calls `ZipFile.extractall()`.

Every archive member is validated before extraction. Restore rejects:

- absolute paths;
- `..`, empty, or dot path components;
- backslashes and NUL characters;
- Windows-invalid and reserved path components;
- members outside the `profile/` root;
- duplicate ZIP names;
- duplicate manifest paths;
- symbolic-link members;
- explicit directory entries;
- nested ZIP encryption;
- any compression method other than `ZIP_STORED`;
- archive members absent from the manifest;
- manifest entries absent from the archive;
- size or SHA-256 mismatches;
- count or total-byte inconsistencies.

Restricting Bundles to stored members eliminates decompression-ratio ambiguity and makes resource accounting exact before extraction.

## 9. Atomic Restore

Restore always creates a generated new Profile ID. It never overwrites an existing Profile.

Flow:

```text
authenticated preview
  -> explicit target alias/display metadata
  -> generated target Profile ID
  -> target ProfileMutationLease
  -> decrypt and revalidate Bundle
  -> extract into target-local .restore staging
  -> verify every written file
  -> atomic replace into target user-data directory
  -> create BrowserProfile catalog record
  -> secret-free runtime event
  -> release target lease
```

The target catalog record is created only after storage extraction succeeds.

If alias creation or catalog insertion fails:

- the generated target storage root is removed;
- no partial Profile remains;
- the preview remains usable for retry with corrected metadata.

## 10. Fresh Authorization Envelope

Profile clone and Bundle restore use a dedicated `ProfileBootstrapTarget` schema.

Allowed target fields:

```text
agent_alias
display_name
agent_description
owner
trust_mode
```

The following fields are not accepted by the control API and are forcibly empty in internal compatibility calls:

```text
bound_agent_ids
allowed_origins
Safety policy ID
Financial policy ID
unknown-effect policy override
persistence override
bootstrap-source override
```

The restored Profile receives:

```text
persistence = persistent
bootstrap_source = restored
bound_agent_ids = []
allowed_origins = []
safety_policy_id = null
financial_policy_id = null
```

Browser identity transport and Agent authorization configuration therefore remain separate operations.

## 11. Protected API

Export:

```text
POST /v1/profiles/{profile_ref}/bootstrap/bundle/export/preview
POST /v1/profiles/{profile_ref}/bootstrap/bundle/export/cancel
POST /v1/profiles/{profile_ref}/bootstrap/bundle/export
```

Restore:

```text
POST /v1/profile-bundles/restore/preview
POST /v1/profile-bundles/restore/cancel
POST /v1/profile-bundles/restore
```

Every endpoint requires the local Visualizer control token.

Restore upload additionally receives the passphrase in the protected local request header. HTTP access logs do not include this header, and WebFA does not copy it into exceptions or events.

## 12. Real Chromium Validation

The real Chromium test:

1. creates a source persistent Profile;
2. writes a persistent Cookie, localStorage value, and IndexedDB value;
3. closes the source Host;
4. exports an encrypted `.webfa-profile` Bundle;
5. authenticates and previews the Bundle;
6. restores it into a new Profile;
7. launches source and restored Profiles concurrently;
8. verifies both initially contain the same identity state;
9. mutates the restored Profile;
10. verifies the source remains unchanged.

This proves encrypted transport, persistence, restoration, and post-restore isolation.

## 13. Adversarial Tests

Coverage includes:

- encryption/decryption roundtrip;
- incorrect passphrase;
- ciphertext tampering;
- path traversal inside an authenticated Bundle;
- non-stored compressed members;
- duplicate/manifest mismatch checks;
- source change after export preview;
- target alias conflict and retry;
- cleanup of unregistered target storage;
- fresh target authorization envelope;
- protected HTTP export/upload/restore;
- Runtime temporary-file cleanup;
- real Chromium identity roundtrip;
- Electron and Renderer type checks;
- production Next and Electron builds.

## 14. Security Boundary

Bundle data never enters:

- MCP tool schemas;
- Agent WebState or BrowserState;
- Monitor events or frames;
- SafetyReceipt;
- local resource grants;
- Profile runtime event payloads;
- redacted previews;
- Electron Renderer memory in the normal desktop streaming path.

The encrypted Bundle itself remains sensitive: loss of the passphrase makes it unrecoverable, while possession of both the Bundle and passphrase grants access to the transported browser identity.

## 15. Profile Bootstrap Completion

Implemented:

```text
human login
Cookie import
Profile clone
WebFA Profile Bundle export
WebFA Profile Bundle restore
```

Post-Core Profile Bootstrap is complete.

Future work may add optional compatibility adapters or externally signed organizational bundles, but these are extensions rather than missing parts of the accepted local Profile Bootstrap model.
