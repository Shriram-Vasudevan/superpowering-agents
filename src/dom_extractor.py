"""Extract a compact, actionable design summary from a captured DOM HTML file.

Raw DOM files can be 100MB+, so this module uses Python's stdlib html.parser
to extract only the signals useful for code generation:
  - CSS class tokens (especially Tailwind utilities)
  - Color values (hex, rgb, oklch, hsl — from inline styles and <style> blocks)
  - Font family names
  - Primitives detected (maps to entries in primitive_registry.json)
  - Layout approach (flex, grid, bento, masonry, horizontal-scroll, etc.)
  - Surface techniques (glassmorphism, noise, spotlight, elevation, etc.)
  - Spacing scale and border-radius tokens

Output is a small dict (~500–3000 bytes) included in every reference entry.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


# ── Regex patterns ─────────────────────────────────────────────────────────

_COLOR_RE = re.compile(
    r"(?:"
    r"#[0-9a-fA-F]{3,8}"
    r"|rgba?\([^)]+\)"
    r"|oklch\([^)]+\)"
    r"|hsl[a]?\([^)]+\)"
    r"|(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime"
    r"|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia"
    r"|pink|rose)-[0-9]{2,3}"
    r")"
)

_FONT_RE = re.compile(r"font-family\s*:\s*([^;\"']+)")

# Tailwind prefixes worth keeping in the class list output
_TW_DESIGN_PREFIXES = (
    "text-", "bg-", "border-", "rounded", "font-", "tracking-",
    "leading-", "shadow", "opacity-", "gradient", "from-", "to-", "via-",
    "flex", "grid", "gap-", "space-", "p-", "px-", "py-", "m-", "mx-", "my-",
    "w-", "h-", "min-", "max-", "overflow-", "z-", "fixed", "absolute",
    "relative", "sticky", "hidden", "block", "inline", "aspect-",
    "col-span-", "row-span-", "backdrop-", "snap-", "animate-",
)


# ── Primitive detection rules ───────────────────────────────────────────────
#
# Each entry maps a primitive id to sets of signals:
#   classes  — substrings to look for in the joined class token string
#   styles   — substrings to look for in the joined inline + style-block text
#   scripts  — substrings to look for in script src URLs + inline script text
#   attrs    — substrings to look for in data-attribute names/values
#   svg_tags — SVG element names that must appear
#   min_hits — how many signals must match (default 1)
#
# Signals are checked as substring containment (case-insensitive for scripts).

_PRIMITIVE_SIGNALS: dict[str, dict[str, Any]] = {

    # ── Animation ───────────────────────────────────────────────────────────
    "motion.framer-motion": {
        "classes": ["motion-", "framer-", "AnimatePresence"],
        "scripts": ["framer-motion", "motion.dev", "/motion/"],
        "attrs": ["data-framer", "data-motion", "data-projection"],
    },
    "motion.gsap": {
        "classes": ["gsap-"],
        "scripts": ["gsap", "ScrollTrigger", "gsap.min.js"],
        "attrs": ["data-gsap"],
    },
    "motion.react-spring": {
        "scripts": ["react-spring", "@react-spring"],
        "classes": ["react-spring"],
    },
    "motion.tailwindcss-animate": {
        "classes": [
            "animate-in", "animate-out", "fade-in", "fade-out",
            "zoom-in", "zoom-out", "slide-in-from-", "slide-out-to-",
            "spin-in", "spin-out",
        ],
        "scripts": ["tailwindcss-animate"],
    },

    # ── Scroll ──────────────────────────────────────────────────────────────
    "scroll.lenis": {
        "classes": ["lenis"],
        "scripts": ["lenis"],
        "attrs": ["data-lenis"],
    },
    "scroll.react-scroll-parallax": {
        "classes": ["parallax-", "react-scroll-parallax"],
        "scripts": ["react-scroll-parallax"],
        "attrs": ["data-parallax"],
    },

    # ── Layout ──────────────────────────────────────────────────────────────
    "layout.bento-grid": {
        # Multiple col-span / row-span values coexisting = bento
        "classes": ["col-span-2", "col-span-3", "row-span-2", "row-span-3", "col-span-full"],
        "min_hits": 2,
    },
    "layout.masonry": {
        "classes": ["masonry", "react-masonry", "masonry-grid"],
        "scripts": ["react-masonry-css", "masonry"],
    },
    "layout.horizontal-scroll-section": {
        "classes": ["overflow-x-scroll", "overflow-x-auto", "snap-x", "snap-mandatory", "snap-start"],
        "styles": ["overflow-x: auto", "overflow-x: scroll", "scroll-snap-type"],
        "min_hits": 1,
    },
    "layout.sticky-scroll-narrative": {
        "classes": ["sticky", "top-0"],
        "styles": ["position: sticky"],
        "min_hits": 2,
    },

    # ── Surface ─────────────────────────────────────────────────────────────
    "surface.glassmorphism": {
        "classes": ["backdrop-blur", "bg-white/", "bg-black/", "backdrop-filter", "bg-opacity"],
        "styles": ["backdrop-filter", "backdrop-blur"],
    },
    "surface.spotlight-hover-card": {
        # Spotlight cards use onMouseMove to update radial-gradient CSS vars
        "styles": ["radial-gradient", "--mouse-x", "--mouse-y", "--spotlight"],
        "classes": ["spotlight", "group-hover"],
        "min_hits": 1,
    },
    "surface.elevated-card": {
        "styles": [
            "box-shadow: 0 1px", "box-shadow: 0 2px", "box-shadow: 0 4px",
            "box-shadow: 0 8px", "box-shadow: rgba",
        ],
        "classes": ["shadow-lg", "shadow-xl", "shadow-2xl", "shadow-md", "hover:shadow"],
        "min_hits": 2,
    },
    "surface.border-card": {
        "classes": ["border", "border-neutral", "border-zinc", "border-slate", "border-gray"],
        "styles": ["border: 1px", "border: 2px"],
        "min_hits": 2,
    },

    # ── Text effects ────────────────────────────────────────────────────────
    "text-effects.outlined-text": {
        "styles": ["-webkit-text-stroke", "text-stroke"],
    },
    "text-effects.typewriter": {
        "classes": ["typewriter", "cursor-blink", "typing-cursor"],
        "scripts": ["typewriter", "typed.js"],
        "attrs": ["data-typewriter", "data-typed"],
    },
    "text-effects.scramble": {
        "classes": ["scramble", "text-scramble"],
        "scripts": ["scramble"],
        "attrs": ["data-scramble"],
    },
    "text-effects.oversized-numerals": {
        # Giant background numbers — look for text-8xl/9xl or very large font sizes
        "classes": ["text-8xl", "text-9xl", "text-[20rem]", "text-[16rem]", "text-[12rem]"],
        "styles": ["font-size: 20rem", "font-size: 16rem", "font-size: 12rem", "font-size: 8rem"],
    },

    # ── Background techniques ───────────────────────────────────────────────
    "background.noise-texture": {
        "svg_tags": ["feTurbulence"],
        "styles": ["feTurbulence", "turbulence", "feBlend", "feComposite"],
        "classes": ["noise-", "grain-", "film-grain"],
    },
    "background.mesh-gradient": {
        "scripts": ["@shadergradient", "shadergradient"],
        "classes": ["mesh-gradient", "gradient-mesh"],
        # Multiple radial-gradients in styles = mesh gradient
        "styles": ["radial-gradient(circle at", "radial-gradient(ellipse"],
    },
    "background.dot-grid": {
        "classes": ["dot-grid", "bg-grid", "bg-dot"],
        "styles": [
            "radial-gradient(circle, ",
            "background-image: radial-gradient",
            "linear-gradient(0deg",
            "background-size:",
        ],
    },
    "background.aurora-gradient": {
        "classes": ["aurora", "animate-aurora", "bg-aurora"],
        "scripts": ["aurora"],
        "styles": ["@keyframes aurora", "animation: aurora"],
    },
    "image-effects.css-svg-filters": {
        "styles": [
            "filter: grayscale", "filter: sepia", "filter: blur",
            "filter: hue-rotate", "filter: contrast", "mix-blend-mode",
            "feColorMatrix", "feBlend",
        ],
        "classes": ["grayscale", "sepia", "saturate-", "hue-rotate-", "mix-blend-"],
    },

    # ── Marquee ─────────────────────────────────────────────────────────────
    "marquee.framer-motion-ticker": {
        "classes": ["marquee", "ticker", "infinite-scroll"],
        "scripts": ["framer-motion"],
        "attrs": ["data-marquee"],
    },
    "marquee.react-fast-marquee": {
        "classes": ["rfm-", "marquee-container", "react-fast-marquee"],
        "scripts": ["react-fast-marquee"],
    },

    # ── Data display / charts ───────────────────────────────────────────────
    "data-display.recharts": {
        "classes": ["recharts-", "recharts-wrapper", "recharts-surface", "recharts-responsive-container"],
        "scripts": ["recharts"],
    },
    "data-display.nivo": {
        "classes": ["nivo-"],
        "scripts": ["@nivo/", "nivo"],
    },
    "data-display.react-flow": {
        "classes": ["react-flow", "react-flow__", "xyflow"],
        "scripts": ["@xyflow/react", "reactflow", "react-flow"],
        "attrs": ["data-reactflow"],
    },
    "data-display.progress-ring": {
        "styles": ["stroke-dasharray", "stroke-dashoffset"],
        "svg_tags": ["circle"],
    },
    "data-display.animated-counter": {
        "classes": ["counter", "count-up", "animate-count"],
        "scripts": ["countup", "react-countup"],
        "attrs": ["data-count", "data-target"],
    },
    "data-display.tanstack-table": {
        "classes": ["tanstack-table", "data-table"],
        "scripts": ["@tanstack/react-table", "tanstack-table"],
        "attrs": ["data-tanstack"],
    },

    # ── Carousel ─────────────────────────────────────────────────────────────
    "carousel.embla": {
        "classes": ["embla", "embla__container", "embla__slide", "embla__viewport"],
        "scripts": ["embla-carousel"],
    },

    # ── Overlay / UI ────────────────────────────────────────────────────────
    "overlay.vaul": {
        "classes": ["vaul-"],
        "scripts": ["vaul"],
        "attrs": ["data-vaul-drawer", "data-vaul"],
    },
    "overlay.cmdk": {
        "classes": ["cmdk-", "[cmdk"],
        "scripts": ["cmdk"],
        "attrs": ["data-cmdk"],
    },
    "feedback.sonner": {
        "classes": ["sonner", "toaster", "[data-sonner"],
        "scripts": ["sonner"],
        "attrs": ["data-sonner-toaster", "data-sonner"],
    },

    # ── Headless UI ─────────────────────────────────────────────────────────
    "ui.radix": {
        "scripts": ["@radix-ui"],
        "attrs": [
            "data-radix-collection-item", "data-state", "data-side",
            "data-align", "data-radix",
        ],
        "classes": ["radix-"],
        "min_hits": 2,
    },
    "ui.react-aria": {
        "scripts": ["react-aria-components", "react-aria"],
        "attrs": ["data-react-aria", "data-rac"],
        "classes": ["react-aria-"],
    },
    "positioning.floating-ui": {
        "scripts": ["@floating-ui", "floating-ui"],
        "attrs": ["data-floating-ui", "data-placement"],
        "classes": ["floating-"],
    },

    # ── Code display ─────────────────────────────────────────────────────────
    "code.shiki": {
        "classes": ["shiki", "shiki-"],
        "scripts": ["shiki"],
        "attrs": ["data-language", "data-theme"],
    },

    # ── 3D ──────────────────────────────────────────────────────────────────
    "3d.react-three-fiber": {
        "scripts": ["@react-three/fiber", "three.min.js", "three.js", "@react-three/drei"],
        "classes": ["r3f-", "drei-"],
    },

    # ── Theming ─────────────────────────────────────────────────────────────
    "theming.oklch-palette": {
        "styles": ["oklch("],
    },

    # ── Loading ──────────────────────────────────────────────────────────────
    "loading.skeleton": {
        "classes": ["react-loading-skeleton", "skeleton-", "animate-pulse"],
        "scripts": ["react-loading-skeleton"],
    },

    # ── Delight ─────────────────────────────────────────────────────────────
    "delight.confetti": {
        "scripts": ["canvas-confetti", "confetti"],
        "classes": ["confetti"],
    },

    # ── Forms ────────────────────────────────────────────────────────────────
    "forms.react-hook-form": {
        "scripts": ["react-hook-form"],
        "attrs": ["data-rhf", "data-react-hook-form"],
    },

    # ── Buttons / CVA ────────────────────────────────────────────────────────
    "buttons.cva": {
        "scripts": ["class-variance-authority", "cva"],
    },

    # ── CMS / platform signals ───────────────────────────────────────────────
    "wordpress": {
        "classes": ["wp-", "elementor", "woocommerce"],
        "scripts": ["wp-includes", "wp-content", "/wp-"],
    },
    "webflow": {
        "classes": ["wf-", "w-layout-"],
        "scripts": ["webflow"],
        "attrs": ["data-wf"],
    },
    "shopify": {
        "classes": ["shopify-"],
        "scripts": ["shopify"],
        "attrs": ["data-shopify"],
    },
    "squarespace": {
        "classes": ["sqsp-", "sqs-"],
        "scripts": ["squarespace"],
        "attrs": ["data-squarespace"],
    },

    # ── General CSS frameworks ───────────────────────────────────────────────
    "tailwind": {
        "classes": ["text-", "bg-", "flex", "grid", "p-", "m-", "gap-", "rounded", "border-"],
        "scripts": ["tailwindcss"],
        "min_hits": 5,
    },
    "bootstrap": {
        "classes": ["col-", "row", "btn", "navbar", "container-fluid", "card-body", "d-flex"],
        "scripts": ["bootstrap"],
        "min_hits": 3,
    },
    "css_modules": {
        "classes": ["__", "_module", "styles_"],
        "min_hits": 3,
    },
}


# ── DOM Parser ─────────────────────────────────────────────────────────────

class _DOMParser(HTMLParser):
    """Collect class tokens, inline styles, style blocks, script srcs, and data attrs."""

    def __init__(self, max_elements: int = 3000):
        super().__init__()
        self.class_counter: Counter[str] = Counter()
        self.inline_styles: list[str] = []
        self.style_blocks: list[str] = []
        self.script_srcs: list[str] = []
        self.inline_scripts: list[str] = []
        self.data_attrs: list[str] = []
        self.svg_tags: set[str] = set()
        self._in_style = False
        self._in_script = False
        self._style_buf: list[str] = []
        self._script_buf: list[str] = []
        self._elements_seen = 0
        self._max_elements = max_elements

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        self._in_style = False
        self._in_script = False

        # Track SVG filter primitives etc.
        svg_primitive_tags = {
            "feturbulen", "feblend", "fecomposite", "fecolormatrix",
            "circle", "path", "ellipse", "polygon",
        }
        if tag.lower() in svg_primitive_tags:
            self.svg_tags.add(tag.lower())

        if self._elements_seen >= self._max_elements:
            return
        self._elements_seen += 1

        attr_map = dict(attrs)

        # Classes
        classes = attr_map.get("class") or ""
        for token in classes.split():
            self.class_counter[token] += 1

        # Inline style
        style = attr_map.get("style") or ""
        if style:
            self.inline_styles.append(style)

        # Data attributes — collect name + value as one string
        for k, v in attrs:
            if k and k.startswith("data-"):
                self.data_attrs.append(f"{k}={v or ''}")

        # Script src
        if tag == "script":
            src = attr_map.get("src") or ""
            if src:
                self.script_srcs.append(src)
            self._in_script = True
            self._script_buf = []

        # Style block
        if tag == "style":
            self._in_style = True
            self._style_buf = []

    def handle_endtag(self, tag: str):
        if tag == "style" and self._in_style:
            content = "".join(self._style_buf)
            self.style_blocks.append(content)
            self._in_style = False
        if tag == "script" and self._in_script:
            content = "".join(self._script_buf)
            if len(content) < 500_000:  # skip huge bundles
                self.inline_scripts.append(content[:50_000])  # cap per script
            self._in_script = False

    def handle_data(self, data: str):
        if self._in_style:
            self._style_buf.append(data)
        elif self._in_script:
            self._script_buf.append(data)


# ── Detection helpers ───────────────────────────────────────────────────────

def _detect_primitives(
    class_str: str,
    style_str: str,
    script_str: str,
    data_attr_str: str,
    svg_tags: set[str],
) -> list[str]:
    """Return list of detected primitive IDs."""
    detected: list[str] = []

    for primitive_id, signals in _PRIMITIVE_SIGNALS.items():
        min_hits = signals.get("min_hits", 1)
        hits = 0

        class_signals = signals.get("classes", [])
        for s in class_signals:
            if s.lower() in class_str.lower():
                hits += 1

        style_signals = signals.get("styles", [])
        for s in style_signals:
            if s.lower() in style_str.lower():
                hits += 1

        script_signals = signals.get("scripts", [])
        for s in script_signals:
            if s.lower() in script_str.lower():
                hits += 1

        attr_signals = signals.get("attrs", [])
        for s in attr_signals:
            if s.lower() in data_attr_str.lower():
                hits += 1

        svg_signals = signals.get("svg_tags", [])
        for s in svg_signals:
            if s.lower() in svg_tags:
                hits += 1

        if hits >= min_hits:
            detected.append(primitive_id)

    return detected


# ── Pre-computed summary cache ──────────────────────────────────────────────
# In remote/deployed mode the raw DOM files are not shipped (too large).
# dom_summaries.json is pre-computed locally and baked into the image instead.

_summary_cache: dict[str, dict[str, Any]] | None = None
_cache_loaded = False


def _load_cache() -> dict[str, dict[str, Any]]:
    global _summary_cache, _cache_loaded
    if _cache_loaded:
        return _summary_cache or {}
    _cache_loaded = True
    candidates = [
        Path(__file__).resolve().parent.parent / "reference_data" / "dom_summaries.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                _summary_cache = json.loads(p.read_text(encoding="utf-8"))
                return _summary_cache
            except Exception:
                pass
    _summary_cache = {}
    return {}


# ── Public API ─────────────────────────────────────────────────────────────

def extract_dom_summary(dom_path: Path | str | None, max_file_bytes: int = 5_000_000) -> dict[str, Any] | None:
    """Parse a DOM HTML file and return a compact design-signal summary.

    Args:
        dom_path: Path to the .html file saved by the capture pipeline.
        max_file_bytes: Read at most this many bytes (default 5 MB).

    Returns:
        Dict with keys: classes, colors, fonts, detected_primitives, layout,
        spacing, border_radius, surface_techniques, class_count.
        Returns None if file missing/unreadable.
    """
    if dom_path is None:
        return None

    path = Path(dom_path)

    # Check pre-computed cache first (used in remote/deployed mode where raw
    # HTML files are not present to keep the Docker image lean).
    cache = _load_cache()
    if cache:
        cached = cache.get(path.name)
        if cached:
            return cached

    if not path.exists():
        return None

    try:
        raw = path.read_bytes()[:max_file_bytes].decode("utf-8", errors="replace")
    except Exception:
        return None

    parser = _DOMParser(max_elements=3000)
    try:
        parser.feed(raw)
    except Exception:
        pass

    class_counter = parser.class_counter

    # Build search strings
    class_str = " ".join(class_counter.keys())
    style_str = " ".join(parser.inline_styles + parser.style_blocks)
    script_str = " ".join(parser.script_srcs + parser.inline_scripts)
    data_attr_str = " ".join(parser.data_attrs)
    svg_tags = parser.svg_tags

    # ── Colors ─────────────────────────────────────────────────────────────
    colors: list[str] = list(dict.fromkeys(_COLOR_RE.findall(style_str)))[:20]

    # ── Fonts ───────────────────────────────────────────────────────────────
    raw_fonts = _FONT_RE.findall(style_str)
    fonts: list[str] = []
    seen_fonts: set[str] = set()
    skip = {"inherit", "initial", "unset", "sans-serif", "serif", "monospace", "system-ui", "ui-sans-serif"}
    for f in raw_fonts:
        clean = f.strip().strip("'\"").split(",")[0].strip().strip("'\"")
        if clean and clean.lower() not in skip and clean not in seen_fonts:
            fonts.append(clean)
            seen_fonts.add(clean)
    fonts = fonts[:8]

    # ── Primitive detection ─────────────────────────────────────────────────
    detected_primitives = _detect_primitives(class_str, style_str, script_str, data_attr_str, svg_tags)

    # ── Design class tokens ─────────────────────────────────────────────────
    design_classes: list[str] = []
    for cls, _ in class_counter.most_common(300):
        if any(cls.startswith(p) for p in _TW_DESIGN_PREFIXES) or len(cls) > 4:
            design_classes.append(cls)
        if len(design_classes) >= 80:
            break

    # ── Layout signals ──────────────────────────────────────────────────────
    layout_tokens = sorted({
        cls for cls in class_counter
        if cls in ("flex", "grid", "inline-flex", "inline-grid", "contents", "table")
        or cls.startswith((
            "flex-", "grid-", "col-", "row-", "place-", "items-", "justify-",
            "col-span-", "row-span-",
        ))
    })[:25]

    # ── Spacing scale ───────────────────────────────────────────────────────
    spacing_tokens = sorted({
        cls for cls in class_counter
        if cls.startswith((
            "p-", "px-", "py-", "pt-", "pb-", "pl-", "pr-",
            "m-", "mx-", "my-", "mt-", "mb-", "ml-", "mr-",
            "gap-", "space-x-", "space-y-",
        ))
    })[:20]

    # ── Border radius ───────────────────────────────────────────────────────
    radius_tokens = sorted({cls for cls in class_counter if cls.startswith("rounded")})[:10]

    # ── Surface techniques (derived from primitives + class analysis) ────────
    surface_techniques: list[str] = []
    if "surface.glassmorphism" in detected_primitives:
        surface_techniques.append("glassmorphism")
    if "background.noise-texture" in detected_primitives:
        surface_techniques.append("noise-grain")
    if "background.aurora-gradient" in detected_primitives:
        surface_techniques.append("aurora-gradient")
    if "background.mesh-gradient" in detected_primitives:
        surface_techniques.append("mesh-gradient")
    if "background.dot-grid" in detected_primitives:
        surface_techniques.append("dot-grid")
    if "text-effects.outlined-text" in detected_primitives:
        surface_techniques.append("outlined-text")
    if "image-effects.css-svg-filters" in detected_primitives:
        surface_techniques.append("image-filters")
    if "oklch" in style_str.lower():
        surface_techniques.append("oklch-colors")

    return {
        "class_count": len(class_counter),
        "classes": design_classes,
        "colors": colors,
        "fonts": fonts,
        "detected_primitives": detected_primitives,
        "surface_techniques": surface_techniques,
        "layout": layout_tokens,
        "spacing": spacing_tokens,
        "border_radius": radius_tokens,
    }
