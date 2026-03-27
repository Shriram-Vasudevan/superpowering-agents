"use client";

type Palette =
  | "forest-green"
  | "warm-earth"
  | "navy-teal"
  | "amber-warm";

const palettes: Record<Palette, string[]> = {
  "forest-green": [
    "oklch(0.30 0.06 150)",
    "oklch(0.28 0.06 145)",
    "oklch(0.26 0.05 140)",
    "oklch(0.24 0.05 135)",
    "oklch(0.22 0.05 130)",
    "oklch(0.21 0.04 125)",
    "oklch(0.20 0.04 120)",
    "oklch(0.19 0.04 115)",
    "oklch(0.18 0.03 110)",
    "oklch(0.17 0.03 105)",
    "oklch(0.16 0.03 100)",
    "oklch(0.16 0.02 95)",
    "oklch(0.15 0.02 90)",
    "oklch(0.15 0.02 80)",
  ],
  "warm-earth": [
    "oklch(0.35 0.06 40)",
    "oklch(0.33 0.06 38)",
    "oklch(0.31 0.05 36)",
    "oklch(0.29 0.05 34)",
    "oklch(0.27 0.05 32)",
    "oklch(0.25 0.04 30)",
    "oklch(0.23 0.04 28)",
    "oklch(0.22 0.04 26)",
    "oklch(0.20 0.03 24)",
    "oklch(0.19 0.03 22)",
    "oklch(0.18 0.03 20)",
    "oklch(0.17 0.02 18)",
  ],
  "navy-teal": [
    "oklch(0.18 0.04 250)",
    "oklch(0.20 0.06 245)",
    "oklch(0.23 0.08 238)",
    "oklch(0.26 0.09 230)",
    "oklch(0.29 0.10 222)",
    "oklch(0.31 0.10 214)",
    "oklch(0.33 0.10 206)",
    "oklch(0.35 0.09 198)",
    "oklch(0.36 0.09 190)",
    "oklch(0.37 0.08 182)",
    "oklch(0.36 0.07 174)",
    "oklch(0.34 0.06 168)",
    "oklch(0.31 0.05 162)",
    "oklch(0.28 0.04 158)",
    "oklch(0.24 0.03 155)",
    "oklch(0.20 0.03 150)",
  ],
  "amber-warm": [
    "oklch(0.42 0.08 60)",
    "oklch(0.40 0.08 58)",
    "oklch(0.38 0.07 55)",
    "oklch(0.36 0.07 52)",
    "oklch(0.34 0.06 49)",
    "oklch(0.32 0.06 46)",
    "oklch(0.30 0.05 43)",
    "oklch(0.28 0.05 40)",
    "oklch(0.26 0.05 37)",
    "oklch(0.24 0.04 34)",
    "oklch(0.22 0.04 31)",
    "oklch(0.21 0.03 28)",
    "oklch(0.20 0.03 25)",
    "oklch(0.19 0.03 22)",
  ],
};

export default function SteppedGradient({
  palette = "forest-green",
  className = "",
  partial,
}: {
  palette?: Palette;
  className?: string;
  partial?: "left" | "right";
}) {
  const colors = palettes[palette];
  return (
    <div
      className={`absolute inset-0 flex pointer-events-none ${partial === "left" ? "w-[60%]" : partial === "right" ? "w-[60%] ml-auto" : ""} ${className}`}
      aria-hidden
    >
      {colors.map((color, i) => (
        <div key={i} className="flex-1 h-full" style={{ backgroundColor: color }} />
      ))}
    </div>
  );
}
