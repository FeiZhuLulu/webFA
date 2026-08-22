export function BrandMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="5 12 54 40" fill="none" aria-hidden="true">
      <rect
        x="6"
        y="13"
        width="52"
        height="38"
        rx="10"
        fill="#FFFFFF"
        stroke="#0A0E14"
        strokeWidth="1.75"
      />
      <rect x="12" y="18.5" width="40" height="5" rx="2.5" fill="#0A0E14" />
      <rect x="12" y="27" width="40" height="18" rx="5" fill="#0A0E14" />
      <path
        d="M24 30.5 L29.5 36 L24 41.5"
        stroke="#33D6FF"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M33.5 41.5 H39.5" stroke="#FFFFFF" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}
