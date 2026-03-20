"""Claude multimodal code generation using design references."""

from __future__ import annotations

import base64
import io
import re
import sys

import anthropic
from PIL import Image

from src.config import settings
from src.retrieval import RetrievalResult

SYSTEM_PROMPT = """\
You are an expert Next.js and Tailwind CSS developer who builds production-quality \
React components by studying real-world design references.

## How this works

You will receive a set of screenshot images from real, professionally designed websites. \
These are your primary source of truth for visual design. The user's text description is \
intentionally simple — people can say "dark gradient" or "move the CTA higher" but they \
cannot verbally describe the precise spacing, color palette, typography hierarchy, or \
layout rhythm that makes a design feel polished. That's what the reference images are for.

Your job is to bridge the gap: take the concrete visual language from the reference \
screenshots (layout structure, color relationships, whitespace patterns, typography \
choices, component arrangements) and combine it with the user's plain-language direction \
(color tweaks, content changes, structural preferences) to produce code that looks like \
it belongs on a real production site.

## How to use the references

- STUDY EACH IMAGE CAREFULLY. Look at the actual pixels — the gradients, shadows, \
border radii, font sizes, spacing ratios, section heights, and visual hierarchy.
- Reproduce the design patterns you see, not generic defaults. If the references use \
a specific card layout with subtle borders and generous padding, replicate that — don't \
fall back to a generic card component.
- Blend across references. Pick the best layout from one, the color treatment from \
another, the typography from a third. The references are a palette, not a single template.
- The user's text modifications override the references. If they say "make it blue" but \
the references are dark, use a blue palette. If they say "single column", ignore \
multi-column layouts in the references.
- Pay attention to the small details that separate amateur from professional: consistent \
spacing scales, proper visual hierarchy (one clear focal point), breathing room between \
sections, and intentional use of contrast.

## Output rules

- Output a single TSX file with a default export
- Use Tailwind CSS for all styling (no CSS modules, no inline styles)
- Include responsive breakpoints (sm, md, lg, xl)
- Use semantic HTML elements
- Include realistic placeholder content (not lorem ipsum)
- Use modern Next.js patterns (App Router compatible)
- The component should be self-contained and immediately renderable
- Wrap your code in a ```tsx code block
"""


def resize_screenshot(path: str | bytes, max_width: int = 1200, max_height: int = 1800) -> bytes:
    """Resize a screenshot to JPEG bytes.

    Resizes to max_width while preserving aspect ratio. Then crops height if the
    screenshot is excessively tall (full-page dumps) — the top portion contains the
    most design-signal (hero, nav, first sections) and is what we want the model to study.
    """
    if isinstance(path, bytes):
        img = Image.open(io.BytesIO(path))
    else:
        img = Image.open(path)

    img = img.convert("RGB")

    # Scale down width first
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height), Image.LANCZOS)

    # Crop height — the top of the page has the most design signal
    if img.height > max_height:
        img = img.crop((0, 0, img.width, max_height))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def build_prompt(user_description: str, results: list[RetrievalResult]) -> list[dict]:
    """Build Claude messages array with interleaved text + image blocks."""
    user_blocks: list[dict] = []

    # Opening text
    user_blocks.append({
        "type": "text",
        "text": f"I want you to build a Next.js component based on this description:\n\n\"{user_description}\"\n\nHere are {len(results)} design references that match this request. Study their visual design, layout, and style carefully:",
    })

    # Interleaved references: image + metadata
    for i, result in enumerate(results, 1):
        # Add screenshot image
        try:
            img_bytes = resize_screenshot(str(result.screenshot_path), settings.max_screenshot_width)
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            user_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img_b64,
                },
            })
        except Exception as e:
            print(f"Warning: could not load screenshot for {result.domain}: {e}", file=sys.stderr)
            continue

        # Add descriptor metadata as text
        desc = result.descriptor
        meta_lines = [
            f"Reference {i}: {result.domain}",
            f"  Style: {desc.get('visual_style', 'N/A')}",
            f"  Layout: {desc.get('layout_pattern', 'N/A')}",
            f"  Typography: {desc.get('typography_style', 'N/A')}",
            f"  Color mode: {desc.get('color_mode', 'N/A')}",
            f"  Industry: {desc.get('industry', 'N/A')}",
            f"  Features: {desc.get('distinguishing_features', 'N/A')}",
        ]
        user_blocks.append({
            "type": "text",
            "text": "\n".join(meta_lines),
        })

    # Final instruction
    user_blocks.append({
        "type": "text",
        "text": (
            "\n\nNow generate a single Next.js TSX component that captures the best design elements "
            "from these references while fulfilling the user's request. The component should use "
            "Tailwind CSS, be responsive, and include realistic content. Output only the TSX code "
            "in a ```tsx code block."
        ),
    })

    return [{"role": "user", "content": user_blocks}]


def extract_code(response_text: str) -> str:
    """Extract TSX code block from Claude's response."""
    pattern = r"```tsx\s*\n(.*?)```"
    match = re.search(pattern, response_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fallback: try any code block
    pattern = r"```\w*\s*\n(.*?)```"
    match = re.search(pattern, response_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Last resort: return the whole response
    return response_text.strip()


def generate_code(
    user_description: str,
    results: list[RetrievalResult],
    system_prompt: str | None = None,
    verbose: bool = False,
) -> str:
    """Call Claude API with multimodal prompt and return generated TSX code."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages = build_prompt(user_description, results)

    if verbose:
        n_images = sum(1 for b in messages[0]["content"] if b.get("type") == "image")
        print(f"Sending prompt with {n_images} images to {settings.model_name}...", file=sys.stderr)

    response = client.messages.create(
        model=settings.model_name,
        max_tokens=4096,
        system=system_prompt or SYSTEM_PROMPT,
        messages=messages,
    )

    response_text = response.content[0].text

    if verbose:
        usage = response.usage
        print(
            f"Response: {usage.input_tokens} input tokens, {usage.output_tokens} output tokens",
            file=sys.stderr,
        )

    return extract_code(response_text)
