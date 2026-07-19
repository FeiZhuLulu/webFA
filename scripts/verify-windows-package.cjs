const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { verifyNsisInstallerPayload } = require("./nsis-installer-verifier.cjs");
const { verifyEmbeddedWindowsIcons } = require("./windows-icon-verifier.cjs");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const mode = process.argv[2];
if (!new Set(["signed", "unsigned"]).has(mode)) {
  throw new Error("Usage: node scripts/verify-windows-package.cjs signed|unsigned");
}

const sourceManifest = require(path.join(root, "package.json"));
const version = sourceManifest.version;
const releaseRoot = path.join(root, ".release/electron");
const unpackedRoot = path.join(releaseRoot, "win-unpacked");
const targets = [
  path.join(unpackedRoot, "WebFA.exe"),
  path.join(unpackedRoot, "resources/sidecar/webfa.exe"),
  path.join(releaseRoot, `WebFA-Setup-${version}-x64.exe`),
];
for (const target of targets) {
  const stat = fs.lstatSync(target);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`Invalid Windows release artifact: ${target}`);
  }
  if (stat.size < 1024 * 1024) throw new Error(`Windows release artifact is unexpectedly small: ${target}`);
}
const embeddedIcons = verifyEmbeddedWindowsIcons(path.join(root, "packaging/webfa.ico"), targets);

const signatureScript = String.raw`
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$securityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
Import-Module -Name $securityModule -Force -ErrorAction Stop
$targets = ConvertFrom-Json $env:WEBFA_SIGNATURE_TARGETS_JSON
[array]$results = foreach ($target in $targets) {
  $signature = Get-AuthenticodeSignature -LiteralPath $target
  $versionInfo = [Diagnostics.FileVersionInfo]::GetVersionInfo($target)
  [pscustomobject]@{
    path = $target
    status = $signature.Status.ToString()
    statusMessage = $signature.StatusMessage
    signerSubject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    signerThumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
    timestampThumbprint = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Thumbprint } else { $null }
    productName = [string]$versionInfo.ProductName
    productVersion = [string]$versionInfo.ProductVersion
    fileVersion = [string]$versionInfo.FileVersion
    fileDescription = [string]$versionInfo.FileDescription
    originalFilename = [string]$versionInfo.OriginalFilename
    internalName = [string]$versionInfo.InternalName
    companyName = [string]$versionInfo.CompanyName
  }
}
ConvertTo-Json -InputObject $results -Compress
`;
const signatures = JSON.parse(execFileSync(
  "powershell.exe",
  ["-NoProfile", "-NonInteractive", "-Command", signatureScript],
  {
    cwd: root,
    encoding: "utf8",
    windowsHide: true,
    env: { ...process.env, WEBFA_SIGNATURE_TARGETS_JSON: JSON.stringify(targets) },
  },
));

const expectedVersionInfo = [
  {
    productName: "WebFA",
    productVersion: `${version}.0`,
    fileVersion: version,
    fileDescription: "WebFA",
    originalFilename: "",
    internalName: "WebFA",
    companyName: "WebFA contributors",
  },
  {
    productName: "WebFA",
    productVersion: version,
    fileVersion: version,
    fileDescription: "WebFA Agent Runtime Sidecar",
    originalFilename: "webfa.exe",
    internalName: "webfa",
    companyName: "WebFA Project",
  },
  {
    productName: "WebFA",
    productVersion: version,
    fileVersion: version,
    fileDescription: sourceManifest.description,
    companyName: "WebFA contributors",
  },
];
for (let index = 0; index < signatures.length; index += 1) {
  for (const [field, expected] of Object.entries(expectedVersionInfo[index])) {
    if (signatures[index][field] !== expected) {
      throw new Error(
        `Windows release version identity changed: ${JSON.stringify({ target: path.basename(targets[index]), field, expected, actual: signatures[index][field] })}`,
      );
    }
  }
}

if (mode === "signed") {
  const approvedThumbprint = process.env.WEBFA_SIGNING_CERT_SHA1?.replaceAll(" ", "").toUpperCase();
  if (!approvedThumbprint || !/^[A-F0-9]{40}$/.test(approvedThumbprint)) {
    throw new Error("Signed release requires an approved WEBFA_SIGNING_CERT_SHA1 thumbprint");
  }
  for (const signature of signatures) {
    if (
      signature.status !== "Valid" ||
      !signature.signerSubject ||
      !signature.signerThumbprint ||
      !signature.timestampThumbprint
    ) {
      throw new Error(`Signed artifact failed Authenticode/timestamp verification: ${JSON.stringify(signature)}`);
    }
    if (signature.signerThumbprint.toUpperCase() !== approvedThumbprint) {
      throw new Error(`Artifact signer is not the approved release certificate: ${JSON.stringify(signature)}`);
    }
  }
  if (new Set(signatures.map((signature) => signature.signerThumbprint)).size !== 1) {
    throw new Error("Windows release artifacts do not share one signing identity");
  }
} else {
  for (const signature of signatures) {
    if (signature.status !== "NotSigned") {
      throw new Error(`Unsigned pipeline produced a signed or invalid artifact: ${JSON.stringify(signature)}`);
    }
  }
}

const installer = targets[2];
verifyNsisInstallerPayload(installer, unpackedRoot).then((nsisInstaller) => {
  const installerSha256 = crypto.createHash("sha256").update(fs.readFileSync(installer)).digest("hex");
  const checksumPath = path.join(releaseRoot, "SHA256SUMS.txt");
  fs.writeFileSync(checksumPath, `${installerSha256}  ${path.basename(installer)}\n`, "utf8");
  const releaseQualified = mode === "signed";
  if (!releaseQualified) {
    process.stderr.write(
      "WARNING: unsigned Windows output is development-only evidence and is not qualified for publication.\n",
    );
  }
  process.stdout.write(`${JSON.stringify({
    status: "pass",
    mode,
    releaseQualified,
    qualification: releaseQualified ? "formal-signed-release" : "development-only-unsigned-artifact",
    version,
    installer,
    installerBytes: fs.statSync(installer).size,
    installerSha256,
    installerCanonicalPePayloadSha256: nsisInstaller.canonicalPePayloadSha256,
    signerSubject: signatures[2].signerSubject,
    timestamped: Boolean(signatures[2].timestampThumbprint),
    checksumPath,
    embeddedIconPixelSha256: embeddedIcons.source.pixelSha256,
    nsisInstaller: {
      appArchiveBytes: nsisInstaller.appArchiveBytes,
      appArchiveSha256: nsisInstaller.appArchiveSha256,
      archiveOffset: nsisInstaller.archiveOffset,
      archiveTailBytes: nsisInstaller.archiveTailBytes,
      embeddedPayloadBundleSha256: nsisInstaller.embeddedPayloadBundleSha256,
      embeddedPayloadFiles: nsisInstaller.embeddedPayloadFiles,
      nsisBytes: nsisInstaller.nsisBytes,
      nsisOffset: nsisInstaller.nsisOffset,
      peSections: nsisInstaller.peSections,
      signedCertificateBytes: nsisInstaller.signedCertificateBytes,
      unsignedPayloadBytes: nsisInstaller.unsignedPayloadBytes,
    },
  })}\n`);
}).catch((error) => {
  process.stderr.write(`${error?.stack ?? error}\n`);
  process.exitCode = 1;
});
