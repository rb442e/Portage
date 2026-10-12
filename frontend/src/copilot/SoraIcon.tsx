import { useId } from "react";

/** Sora mark: a gradient tile with a flowing "S" ribbon and a spark. Same artwork as public/sora.svg. */
export default function SoraIcon({ size = 24, className }: { size?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} role="img" aria-label="Sora">
      <defs>
        <linearGradient id={`${id}bg`} x1="6" y1="2" x2="58" y2="62" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#6366F1" />
          <stop offset="0.55" stopColor="#3B82F6" />
          <stop offset="1" stopColor="#06B6D4" />
        </linearGradient>
        <linearGradient id={`${id}sh`} x1="32" y1="0" x2="32" y2="36" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#fff" stopOpacity=".3" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill={`url(#${id}bg)`} />
      <rect width="64" height="64" rx="16" fill={`url(#${id}sh)`} />
      <path d="M43 22C40 16.5 31 14.5 25.5 18.5C20 22.5 22.5 29 32 31.5C41.5 34 44 40.5 38.5 45.5C33 50 24 48.5 21 42"
        fill="none" stroke="#fff" strokeWidth="5.2" strokeLinecap="round" strokeLinejoin="round" />
      <path transform="translate(2 -1.5)" d="M49 9c.7 3.4 2.5 5.2 6 6-3.5.7-5.3 2.5-6 6-.7-3.5-2.5-5.3-6-6 3.5-.8 5.3-2.6 6-6z" fill="#CFFAFE" />
    </svg>
  );
}
