const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const { isDeepStrictEqual } = require("node:util");
const ResEdit = require("resedit");

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const DEFAULT_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256];

function validateWindowsIcon(iconPath, expectedSizes = DEFAULT_SIZES) {
  const stat = fs.lstatSync(iconPath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`Invalid Windows icon file: ${iconPath}`);
  }

  const bytes = fs.readFileSync(iconPath);
  if (bytes.length < 6 || bytes.readUInt16LE(0) !== 0 || bytes.readUInt16LE(2) !== 1) {
    throw new Error(`Invalid ICO header: ${iconPath}`);
  }
  const count = bytes.readUInt16LE(4);
  const directoryEnd = 6 + count * 16;
  if (count !== expectedSizes.length || directoryEnd > bytes.length) {
    throw new Error(`Unexpected ICO image count: ${count}`);
  }

  const sizes = [];
  let expectedOffset = directoryEnd;
  for (let index = 0; index < count; index += 1) {
    const entry = 6 + index * 16;
    const width = bytes[entry] || 256;
    const height = bytes[entry + 1] || 256;
    const colorCount = bytes[entry + 2];
    const reserved = bytes[entry + 3];
    const planes = bytes.readUInt16LE(entry + 4);
    const bitsPerPixel = bytes.readUInt16LE(entry + 6);
    const imageBytes = bytes.readUInt32LE(entry + 8);
    const imageOffset = bytes.readUInt32LE(entry + 12);
    const imageEnd = imageOffset + imageBytes;
    if (
      width !== height ||
      colorCount !== 0 ||
      reserved !== 0 ||
      planes !== 1 ||
      bitsPerPixel !== 32 ||
      imageBytes < 33 ||
      imageOffset !== expectedOffset ||
      imageEnd > bytes.length
    ) {
      throw new Error(`Invalid ICO directory entry for ${width}x${height}`);
    }
    const isPng = bytes.subarray(imageOffset, imageOffset + PNG_SIGNATURE.length).equals(PNG_SIGNATURE);
    if (width === 256) {
      validatePngFrame(bytes.subarray(imageOffset, imageEnd), width, height);
    } else if (
      isPng ||
      imageBytes !== 40 + width * height * 4 ||
      bytes.readUInt32LE(imageOffset) !== 40 ||
      bytes.readInt32LE(imageOffset + 4) !== width ||
      bytes.readInt32LE(imageOffset + 8) !== height * 2 ||
      bytes.readUInt16LE(imageOffset + 12) !== 1 ||
      bytes.readUInt16LE(imageOffset + 14) !== 32 ||
      bytes.readUInt32LE(imageOffset + 16) !== 0 ||
      bytes.readUInt32LE(imageOffset + 20) !== width * height * 4
    ) {
      throw new Error(`ICO DIB frame has an unexpected format: ${width}x${height}`);
    }
    sizes.push(width);
    expectedOffset = imageEnd;
  }
  if (expectedOffset !== bytes.length || JSON.stringify(sizes) !== JSON.stringify(expectedSizes)) {
    throw new Error(`ICO frame set or trailing data is invalid: ${sizes.join(",")}`);
  }

  return {
    bytes: bytes.length,
    frames: count,
    sizes,
    sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
  };
}

function verifyEmbeddedWindowsIcons(sourceIcon, executablePaths) {
  if (process.platform !== "win32") {
    throw new Error("Embedded Windows icon verification requires Windows");
  }
  if (!Array.isArray(executablePaths) || executablePaths.length === 0) {
    throw new Error("At least one executable is required for embedded icon verification");
  }
  const sourceResourceIdentity = readSourceIconResourceIdentity(sourceIcon);
  const resourceResults = executablePaths.map((target) => {
    const groups = readPortableExecutableIconGroups(target);
    const matches = groups.filter((group) => isDeepStrictEqual(group.icons, sourceResourceIdentity));
    if (matches.length === 0) {
      throw new Error(
        `Executable has no complete icon resource group matching the verified source: ${target} ` +
        `(groups=${JSON.stringify(groups.map((group) => group.icons.map((icon) => icon.width)))})`,
      );
    }
    return { path: target, groups: groups.length, matchingGroups: matches.length, frames: sourceResourceIdentity.length };
  });

  const script = String.raw`
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Drawing

function Get-IconPixelIdentity([System.Drawing.Icon]$Icon) {
  if ($null -eq $Icon) { throw "Executable does not expose an associated icon" }
  $bitmap = $Icon.ToBitmap()
  try {
    if ($bitmap.Width -ne 32 -or $bitmap.Height -ne 32) {
      throw "Expected a 32x32 application icon, got $($bitmap.Width)x$($bitmap.Height)"
    }
    $pixels = New-Object byte[] ($bitmap.Width * $bitmap.Height * 4)
    $offset = 0
    for ($y = 0; $y -lt $bitmap.Height; $y++) {
      for ($x = 0; $x -lt $bitmap.Width; $x++) {
        $pixel = $bitmap.GetPixel($x, $y)
        # Fully transparent RGB channels are not rendered and may be normalized
        # differently when an ICO frame is rewritten into a PE resource.
        $pixels[$offset] = if ($pixel.A -eq 0) { 0 } else { $pixel.R }
        $pixels[$offset + 1] = if ($pixel.A -eq 0) { 0 } else { $pixel.G }
        $pixels[$offset + 2] = if ($pixel.A -eq 0) { 0 } else { $pixel.B }
        $pixels[$offset + 3] = $pixel.A
        $offset += 4
      }
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
      $hash = ($sha.ComputeHash($pixels) | ForEach-Object ToString x2) -join ""
    } finally {
      $sha.Dispose()
    }
    [pscustomobject]@{ width = $bitmap.Width; height = $bitmap.Height; pixelSha256 = $hash }
  } finally {
    $bitmap.Dispose()
  }
}

$request = ConvertFrom-Json $env:WEBFA_ICON_VERIFICATION_JSON
$source = [System.Drawing.Icon]::new([string]$request.sourceIcon, 32, 32)
try {
  $sourceIdentity = Get-IconPixelIdentity $source
} finally {
  $source.Dispose()
}

[array]$executables = foreach ($target in $request.executables) {
  $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($target)
  try {
    $identity = Get-IconPixelIdentity $icon
  } finally {
    if ($null -ne $icon) { $icon.Dispose() }
  }
  [pscustomobject]@{ path = $target; width = $identity.width; height = $identity.height; pixelSha256 = $identity.pixelSha256 }
}

[pscustomobject]@{ source = $sourceIdentity; executables = $executables } | ConvertTo-Json -Depth 4 -Compress
`;
  const result = JSON.parse(execFileSync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", script],
    {
      encoding: "utf8",
      windowsHide: true,
      env: {
        ...process.env,
        WEBFA_ICON_VERIFICATION_JSON: JSON.stringify({ sourceIcon, executables: executablePaths }),
      },
    },
  ));
  for (const executable of result.executables) {
    if (executable.pixelSha256 !== result.source.pixelSha256) {
      throw new Error(
        `Embedded application icon differs from the verified source: ${executable.path} ` +
        `(source=${result.source.pixelSha256}, embedded=${executable.pixelSha256})`,
      );
    }
  }
  result.resourceGroups = resourceResults;
  return result;
}

function readSourceIconResourceIdentity(sourceIcon) {
  const iconFile = ResEdit.Data.IconFile.from(fs.readFileSync(sourceIcon));
  return iconFile.icons.map((item) => iconResourceIdentity(item.data, item))
    .sort((left, right) => left.width - right.width);
}

function readPortableExecutableIconGroups(target) {
  // Authenticode is verified separately. `ignoreCert` only allows read-only
  // resource parsing without asking ResEdit to rewrite a signed executable.
  const executable = ResEdit.NtExecutable.from(fs.readFileSync(target), { ignoreCert: true });
  const resources = ResEdit.NtExecutableResource.from(executable);
  return ResEdit.Resource.IconGroupEntry.fromEntries(resources.entries).map((group) => ({
    id: group.id,
    lang: group.lang,
    icons: group.getIconItemsFromEntries(resources.entries)
      .map((item) => {
        const itemWidth = normalizeIconDimension(item.width ?? item.bitmapInfo?.width);
        const itemHeight = normalizeIconDimension(
          item.height ?? (item.isIcon() && item.masks !== null
            ? Math.floor(item.bitmapInfo.height / 2)
            : item.bitmapInfo?.height),
        );
        // PyInstaller keeps the original maskless 32-bit ICO dataSize in
        // RT_GROUP_ICON while its RT_ICON resource contains the equivalent
        // synthesized zero AND mask. Electron/rcedit records the expanded
        // size. Accept only these two exact encodings, then compare pixels and
        // masks semantically below.
        const acceptedDataSizes = item.isRaw()
          ? [item.bin.byteLength]
          : [40 + item.pixels.byteLength, item.generate().byteLength];
        const metadataMatches = group.icons.filter((candidate) => (
          normalizeIconDimension(candidate.width) === itemWidth &&
          normalizeIconDimension(candidate.height) === itemHeight &&
          candidate.bitCount === (item.bitCount ?? item.bitmapInfo?.bitCount) &&
          acceptedDataSizes.includes(candidate.dataSize)
        ));
        if (metadataMatches.length !== 1) {
          throw new Error(`PE icon group metadata is inconsistent: ${target}`);
        }
        const [metadata] = metadataMatches;
        return iconResourceIdentity(item, metadata);
      })
      .sort((left, right) => left.width - right.width),
  }));
}

function iconResourceIdentity(item, metadata) {
  const width = normalizeIconDimension(metadata.width ?? item.width ?? item.bitmapInfo?.width);
  const height = normalizeIconDimension(metadata.height ?? item.height ?? item.bitmapInfo?.height);
  const bitCount = metadata.bitCount ?? item.bitCount ?? item.bitmapInfo?.bitCount;
  const planes = metadata.planes ?? item.bitmapInfo?.planes ?? 1;
  if (item.isRaw()) {
    return {
      width,
      height,
      planes,
      bitCount,
      encoding: "png",
      imageSha256: crypto.createHash("sha256").update(Buffer.from(item.bin)).digest("hex"),
    };
  }
  return {
    width,
    height,
    planes,
    bitCount,
    encoding: "dib",
    pixelSha256: crypto.createHash("sha256").update(Buffer.from(item.pixels)).digest("hex"),
    maskSha256: crypto.createHash("sha256").update(Buffer.from(item.masks)).digest("hex"),
  };
}

function normalizeIconDimension(value) {
  return value === 0 ? 256 : value;
}

function validatePngFrame(frame, expectedWidth, expectedHeight) {
  if (frame.length < 45 || !frame.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE)) {
    throw new Error(`ICO PNG frame has an unexpected format: ${expectedWidth}x${expectedHeight}`);
  }

  let offset = PNG_SIGNATURE.length;
  let chunkIndex = 0;
  let sawIdat = false;
  let sawIend = false;
  while (offset < frame.length) {
    if (frame.length - offset < 12) {
      throw new Error(`ICO PNG frame has a truncated chunk: ${expectedWidth}x${expectedHeight}`);
    }
    const dataLength = frame.readUInt32BE(offset);
    const dataStart = offset + 8;
    const dataEnd = dataStart + dataLength;
    const chunkEnd = dataEnd + 4;
    if (dataEnd < dataStart || chunkEnd > frame.length) {
      throw new Error(`ICO PNG frame has a truncated chunk: ${expectedWidth}x${expectedHeight}`);
    }
    const chunkType = frame.subarray(offset + 4, offset + 8).toString("ascii");
    const storedCrc = frame.readUInt32BE(dataEnd);
    const computedCrc = crc32(frame.subarray(offset + 4, dataEnd));
    if (storedCrc !== computedCrc) {
      throw new Error(`ICO PNG chunk CRC is invalid (${chunkType}): ${expectedWidth}x${expectedHeight}`);
    }

    if (chunkIndex === 0) {
      if (
        chunkType !== "IHDR" ||
        dataLength !== 13 ||
        frame.readUInt32BE(dataStart) !== expectedWidth ||
        frame.readUInt32BE(dataStart + 4) !== expectedHeight ||
        frame[dataStart + 8] !== 8 ||
        frame[dataStart + 9] !== 6 ||
        frame[dataStart + 10] !== 0 ||
        frame[dataStart + 11] !== 0 ||
        frame[dataStart + 12] !== 0
      ) {
        throw new Error(`ICO PNG frame has an unexpected format: ${expectedWidth}x${expectedHeight}`);
      }
    } else if (chunkType === "IHDR") {
      throw new Error(`ICO PNG frame has multiple IHDR chunks: ${expectedWidth}x${expectedHeight}`);
    }

    if (chunkType === "IDAT") sawIdat = true;
    if (chunkType === "IEND") {
      if (dataLength !== 0 || !sawIdat || chunkEnd !== frame.length) {
        throw new Error(`ICO PNG IEND is invalid: ${expectedWidth}x${expectedHeight}`);
      }
      sawIend = true;
    }
    if (sawIend && chunkEnd !== frame.length) {
      throw new Error(`ICO PNG frame has trailing chunks: ${expectedWidth}x${expectedHeight}`);
    }
    offset = chunkEnd;
    chunkIndex += 1;
  }
  if (!sawIend) {
    throw new Error(`ICO PNG frame is missing IEND: ${expectedWidth}x${expectedHeight}`);
  }
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const value of bytes) {
    crc ^= value;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

module.exports = {
  validateWindowsIcon,
  verifyEmbeddedWindowsIcons,
};
