"""Layout issue detection using Playwright headless rendering.

Navigates to a URL, injects a DOM-walking detection script, finds visual layout
problems (sibling overlaps, content overflow, collapsed containers, off-viewport
elements), annotates them with numbered colored boxes, takes a screenshot, and
returns structured issue data for the agent to triage.

The agent decides which issues to fix — this module only detects and reports.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any


# ── Detection script (injected into page via page.evaluate()) ─────────────

_DETECTION_JS = """
() => {
  const MIN_AREA = 400;          // px² — ignore tiny elements
  const OVERLAP_MIN_PX = 4;      // px² — ignore rounding artifacts

  function getPageRect(el) {
    const r = el.getBoundingClientRect();
    // At scroll Y=0, getBoundingClientRect() == page-absolute coordinates.
    return {
      top:    Math.round(r.top),
      left:   Math.round(r.left),
      bottom: Math.round(r.bottom),
      right:  Math.round(r.right),
      width:  Math.round(r.width),
      height: Math.round(r.height),
    };
  }

  function isVisible(el) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (parseFloat(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  }

  function rectsOverlap(a, b) {
    return !(a.right <= b.left || b.right <= a.left ||
             a.bottom <= b.top  || b.bottom <= a.top);
  }

  function overlapArea(a, b) {
    const w = Math.min(a.right, b.right)   - Math.max(a.left, b.left);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.top,  b.top);
    return w * h;
  }

  function getSelector(el) {
    if (el.id) return '#' + el.id;
    const parts = [];
    let cur = el;
    for (let depth = 0; depth < 4 && cur && cur !== document.body; depth++) {
      let part = cur.tagName.toLowerCase();
      const cls = [...cur.classList].filter(c => !c.startsWith('__lc')).slice(0, 2);
      if (cls.length) part += '.' + cls.join('.');
      const siblings = cur.parentElement
        ? [...cur.parentElement.children].filter(c => c.tagName === cur.tagName)
        : [];
      if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(cur) + 1) + ')';
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(' > ') || el.tagName.toLowerCase();
  }

  function intentionalityScore(elA, elB) {
    const sA = getComputedStyle(elA);
    const sB = getComputedStyle(elB);
    const posA = sA.position;
    const posB = sB.position;
    const zA = parseInt(sA.zIndex) || 0;
    const zB = parseInt(sB.zIndex) || 0;

    // Both non-static with different z-index → almost certainly deliberate layering
    if (posA !== 'static' && posB !== 'static' && zA !== zB) return 0.9;
    // One absolutely positioned → could be intentional overlay
    if (posA === 'absolute' || posB === 'absolute') return 0.55;
    // One fixed/sticky → probably navbar or CTA overlap, intentional
    if (posA === 'fixed' || posB === 'fixed' || posA === 'sticky' || posB === 'sticky') return 0.8;
    // Both static in a normal flow → strong signal this is a bug
    return 0.1;
  }

  const issues = [];
  let issueId = 1;

  // ── 1. Sibling overlap ───────────────────────────────────────────────────
  // Check immediate children of every parent. Parent-child overlap is always
  // intentional; sibling overlap is where layout bugs appear.
  const visitedParents = new WeakSet();
  document.querySelectorAll('body *').forEach(el => {
    const parent = el.parentElement;
    if (!parent || visitedParents.has(parent)) return;
    visitedParents.add(parent);

    const children = [...parent.children].filter(isVisible);
    if (children.length < 2) return;

    for (let i = 0; i < children.length; i++) {
      for (let j = i + 1; j < children.length; j++) {
        const a = children[i], b = children[j];
        const rA = getPageRect(a), rB = getPageRect(b);

        if (rA.width * rA.height < MIN_AREA || rB.width * rB.height < MIN_AREA) continue;
        if (!rectsOverlap(rA, rB)) continue;

        const area = overlapArea(rA, rB);
        if (area < OVERLAP_MIN_PX) continue;

        const iScore = intentionalityScore(a, b);
        issues.push({
          id: issueId++,
          type: 'sibling_overlap',
          severity: iScore < 0.3 ? 'high' : iScore < 0.6 ? 'medium' : 'low',
          element_a: { selector: getSelector(a), rect: rA, tag: a.tagName.toLowerCase() },
          element_b: { selector: getSelector(b), rect: rB, tag: b.tagName.toLowerCase() },
          overlap_area_px2: Math.round(area),
          intentionality_score: iScore,
          note: iScore < 0.3
            ? 'Both elements are in normal flow — likely a layout bug.'
            : iScore < 0.6
            ? 'One element is positioned — may be intentional. Verify visually.'
            : 'Different z-index stacking — probably intentional design.',
        });
      }
    }
  });

  // ── 2. Horizontal content overflow ──────────────────────────────────────
  document.querySelectorAll('body *').forEach(el => {
    if (!isVisible(el)) return;
    const s = getComputedStyle(el);
    const ovfX = s.overflowX;
    if (ovfX === 'hidden' || ovfX === 'auto' || ovfX === 'scroll') return;
    if (el.scrollWidth <= el.clientWidth + 2) return;

    const r = getPageRect(el);
    if (r.width * r.height < MIN_AREA) return;

    issues.push({
      id: issueId++,
      type: 'horizontal_overflow',
      severity: 'medium',
      element: { selector: getSelector(el), rect: r, tag: el.tagName.toLowerCase() },
      overflow_px: el.scrollWidth - el.clientWidth,
      intentionality_score: 0.05,
      note: `Content overflows by ${el.scrollWidth - el.clientWidth}px horizontally. Usually causes horizontal scroll on the page.`,
    });
  });

  // ── 3. Collapsed containers with content ────────────────────────────────
  // Common cause: next/image without explicit height, flex parent with no height.
  document.querySelectorAll('body *').forEach(el => {
    if (!isVisible(el)) return;
    const r = getPageRect(el);
    const s = getComputedStyle(el);
    if (r.height > 0) return;
    if (el.childElementCount === 0) return;
    // Ignore elements that are meant to be zero-height (e.g. separators)
    if (el.tagName === 'HR' || el.tagName === 'BR') return;

    issues.push({
      id: issueId++,
      type: 'collapsed_container',
      severity: 'high',
      element: {
        selector: getSelector(el),
        tag: el.tagName.toLowerCase(),
        child_count: el.childElementCount,
      },
      intentionality_score: 0.02,
      note: `Element has height:0 but contains ${el.childElementCount} child element(s). ` +
            'Common cause: next/image missing explicit height, or flex parent with no height constraint.',
    });
  });

  // ── 4. Off-viewport elements (left/right) ───────────────────────────────
  const vw = window.innerWidth;
  document.querySelectorAll('body *').forEach(el => {
    if (!isVisible(el)) return;
    const r = getPageRect(el);
    if (r.width * r.height < MIN_AREA) return;
    const s = getComputedStyle(el);
    if (s.position === 'fixed' || s.position === 'absolute') return; // likely intentional

    if (r.right < -20 || r.left > vw + 20) {
      issues.push({
        id: issueId++,
        type: 'off_viewport',
        severity: 'high',
        element: { selector: getSelector(el), rect: r, tag: el.tagName.toLowerCase() },
        direction: r.right < -20 ? 'left' : 'right',
        intentionality_score: 0.05,
        note: `Element is ${r.right < -20 ? 'left' : 'right'} of viewport — content is invisible to users.`,
      });
    }
  });

  return issues;
}
"""


# ── Visual richness detection (injected separately) ──────────────────────

_RICHNESS_JS = """
() => {
  const issues = [];
  let issueId = 1;

  // Helper: get all "section-level" elements (direct children of main/body, or semantic sections)
  function getSections() {
    const sections = [];
    // Try semantic elements first
    const semanticSections = document.querySelectorAll('main > section, main > div, body > section, body > div > section');
    if (semanticSections.length >= 3) {
      semanticSections.forEach(s => {
        const r = s.getBoundingClientRect();
        if (r.height > 100 && r.width > 200) sections.push(s);
      });
    }
    // Fallback: direct children of main or first major container
    if (sections.length < 3) {
      const main = document.querySelector('main') || document.body;
      [...main.children].forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.height > 100 && r.width > 200) sections.push(el);
      });
    }
    return sections;
  }

  const sections = getSections();

  sections.forEach((section, idx) => {
    const styles = getComputedStyle(section);
    const rect = section.getBoundingClientRect();
    const sectionSignals = [];
    const sectionWarnings = [];

    // 1. Check background treatment
    const bg = styles.backgroundColor;
    const bgImage = styles.backgroundImage;
    const hasBackgroundImage = bgImage && bgImage !== 'none';

    // Rich background = gradient, mesh, aurora, image, pattern — NOT just a flat color
    // Check both the section itself AND its children
    const richBgPatterns = ['gradient', 'noise', 'dot-grid', 'mesh', 'aurora', 'pattern', 'backdrop-blur'];
    const sectionClasses = section.className || '';
    const hasSelfRichBg = richBgPatterns.some(p => sectionClasses.includes(p));
    const hasChildRichBg = section.querySelector(
      '[class*="gradient"], [class*="noise"], [class*="dot-grid"], [class*="mesh"], ' +
      '[class*="aurora"], [class*="pattern"], [class*="backdrop-blur"]'
    );
    const hasRichBgClass = hasSelfRichBg || hasChildRichBg;

    const hasImageChild = section.querySelector(
      'img[style*="object-cover"], img[class*="object-cover"], ' +
      '[style*="background-image"], [class*="object-cover"]'
    );
    // Fill images that serve as section backgrounds (not small content images)
    const hasFillImage = section.querySelector('img[class*="object-cover"][style*="position"]') ||
      section.querySelector('[class*="relative"] > img[class*="object-cover"]');

    // Check both section itself and children for overlays
    const overlayPatterns = ['overlay', 'noise', 'grain', 'texture'];
    const hasSelfOverlay = overlayPatterns.some(p => sectionClasses.includes(p));
    const hasChildOverlay = section.querySelector(
      '[class*="overlay"], [class*="noise"], [class*="grain"], [class*="texture"]'
    );
    const hasOverlayChild = hasSelfOverlay || hasChildOverlay;

    if (hasBackgroundImage || hasRichBgClass || hasFillImage) {
      sectionSignals.push('has-background-treatment');
    }
    if (hasOverlayChild) {
      sectionSignals.push('has-texture-overlay');
    }

    // Plain = white/near-white/transparent with no rich background treatment
    const isNearWhite = (c) => {
      if (!c) return true;
      if (c === 'rgba(0, 0, 0, 0)' || c === 'transparent') return true;
      const m = c.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (m && parseInt(m[1]) > 235 && parseInt(m[2]) > 235 && parseInt(m[3]) > 235) return true;
      return false;
    };
    // Also check near-white grays like bg-slate-50 (#f8fafc = rgb(248,250,252))
    const isPlainBackground = !hasBackgroundImage && !hasRichBgClass && !hasFillImage && isNearWhite(bg);
    if (isPlainBackground && !hasOverlayChild) {
      sectionWarnings.push('plain-white-background');
    }

    // 2. Check for surface depth indicators
    const hasGlassmorphism = section.querySelector('[class*="glass"], [class*="backdrop-blur"], [style*="backdrop-filter"]');
    const hasShadow = styles.boxShadow && styles.boxShadow !== 'none';
    const childrenWithShadow = section.querySelectorAll('[class*="shadow"]').length;
    const hasSpotlight = section.querySelector('[class*="spotlight"], [class*="hover-card"]');
    const hasBorder = section.querySelector('[class*="border-"]');

    if (hasGlassmorphism) sectionSignals.push('glassmorphism');
    if (hasShadow || childrenWithShadow > 0) sectionSignals.push('shadow-depth');
    if (hasSpotlight) sectionSignals.push('spotlight-effect');
    if (hasBorder) sectionSignals.push('border-treatment');

    // 3. Check typography scale
    const headings = section.querySelectorAll('h1, h2, h3');
    let maxFontSize = 0;
    headings.forEach(h => {
      const fs = parseFloat(getComputedStyle(h).fontSize);
      if (fs > maxFontSize) maxFontSize = fs;
    });
    if (maxFontSize >= 48) sectionSignals.push('large-typography');
    if (maxFontSize > 0 && maxFontSize < 28) sectionWarnings.push('small-headings');

    // 4. Check for animation attributes (framer-motion, CSS animations)
    const hasMotion = section.querySelector('[style*="transform"], [style*="opacity"], [class*="motion"], [data-framer], [class*="animate"]');
    const hasTransition = section.querySelector('[class*="transition"]');
    if (hasMotion || hasTransition) sectionSignals.push('has-animation');

    // 5. Check for images with visual treatment
    const images = section.querySelectorAll('img');
    const hasImages = images.length > 0;
    if (hasImages) sectionSignals.push('has-images');
    const hasImageTreatment = section.querySelector('[class*="grain"], [class*="duotone"], [class*="filter"], [class*="image-grain"]');
    if (hasImageTreatment) sectionSignals.push('image-visual-treatment');

    // 6. Check color diversity within section
    const colorElements = section.querySelectorAll('[class*="text-"], [class*="bg-"]');
    const uniqueColors = new Set();
    colorElements.forEach(el => {
      const c = getComputedStyle(el).color;
      if (c) uniqueColors.add(c);
    });
    if (uniqueColors.size >= 3) sectionSignals.push('color-diversity');

    // 7. Layout complexity
    const hasGrid = section.querySelector('[class*="grid"]');
    const hasFlex = section.querySelector('[class*="flex"]');
    const hasAsymmetric = section.querySelector('[class*="col-span-2"], [class*="col-span-3"], [class*="row-span"]');
    if (hasGrid) sectionSignals.push('uses-grid');
    if (hasAsymmetric) sectionSignals.push('asymmetric-layout');

    // Compute richness score (0-10)
    // Subtle treatments (noise, dot-grid alone) count as partial credit
    const subtleOnlySignals = ['has-texture-overlay', 'border-treatment', 'has-animation', 'uses-grid'];
    const strongSignals = sectionSignals.filter(s => !subtleOnlySignals.includes(s));
    const richnessScore = Math.min(10, strongSignals.length * 2 + (sectionSignals.length - strongSignals.length));

    // Template-grade: low richness OR only subtle/structural signals (no bold visual investment)
    const isTemplateGrade = richnessScore <= 3 || (strongSignals.length <= 1 && sectionWarnings.length > 0);

    if (isTemplateGrade) {
      issues.push({
        id: issueId++,
        type: 'low_visual_richness',
        severity: richnessScore <= 1 ? 'high' : 'medium',
        section_index: idx + 1,
        element: {
          selector: section.tagName.toLowerCase() + (section.className ? '.' + [...section.classList].slice(0, 2).join('.') : ''),
          rect: {
            top: Math.round(rect.top),
            left: Math.round(rect.left),
            bottom: Math.round(rect.bottom),
            right: Math.round(rect.right),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          },
          tag: section.tagName.toLowerCase(),
        },
        richness_score: richnessScore,
        signals_present: sectionSignals,
        warnings: sectionWarnings,
        intentionality_score: 0.1,
        note: `Section ${idx + 1} has richness score ${richnessScore}/10 with ${sectionWarnings.length} warning(s): ${sectionWarnings.join(', ') || 'none'}. ` +
              `This section looks template-grade. Add background treatments (gradient, noise, texture), ` +
              `surface depth (glassmorphism, shadows, spotlight), or visual effects.`,
      });
    }
  });

  // Overall page richness — count sections with REAL visual treatments
  let sectionsWithBg = 0;
  const treatmentPatterns = ['gradient', 'noise', 'mesh', 'aurora', 'backdrop-blur', 'pattern', 'dot-grid'];
  sections.forEach(s => {
    const sClasses = s.className || '';
    const hasSelfTreatment = treatmentPatterns.some(p => sClasses.includes(p));
    const hasChildTreatment = s.querySelector(
      '[class*="gradient"], [class*="noise"], [class*="mesh"], [class*="aurora"], ' +
      '[class*="backdrop-blur"], [class*="pattern"], [class*="dot-grid"]'
    );
    const hasBgImage = getComputedStyle(s).backgroundImage !== 'none';
    const hasFillImg = s.querySelector('img[class*="object-cover"]');
    const bgColor = getComputedStyle(s).backgroundColor;
    // Dark sections count as treated (bg-slate-900 etc)
    const m = bgColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    const isDark = m && parseInt(m[1]) < 60 && parseInt(m[2]) < 60 && parseInt(m[3]) < 60;
    if (hasSelfTreatment || hasChildTreatment || hasBgImage || hasFillImg || isDark) sectionsWithBg++;
  });
  if (sections.length > 0 && sectionsWithBg / sections.length < 0.3) {
    issues.push({
      id: issueId++,
      type: 'page_visual_monotony',
      severity: 'high',
      element: { selector: 'body', tag: 'body', rect: { top: 0, left: 0, bottom: 0, right: 0, width: 0, height: 0 } },
      intentionality_score: 0.05,
      note: `Only ${sectionsWithBg}/${sections.length} sections have background treatments. ` +
            `The page will look flat and monotonous. Award-winning sites alternate between ` +
            `different background treatments (gradient, texture, dark/light, image) across sections.`,
      sections_total: sections.length,
      sections_with_background: sectionsWithBg,
    });
  }

  return issues;
}
"""


# ── Annotation script (injected after detection) ─────────────────────────

_ANNOTATE_JS = """
(issues) => {
  // Remove any previous overlay
  const existing = document.getElementById('__lc_overlay__');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = '__lc_overlay__';
  overlay.style.cssText = [
    'position:absolute', 'top:0', 'left:0',
    'width:100%', 'height:' + document.documentElement.scrollHeight + 'px',
    'pointer-events:none', 'z-index:2147483647',
  ].join(';');
  document.documentElement.appendChild(overlay);

  const COLORS = { high: '#ef4444', medium: '#f97316', low: '#eab308' };

  issues.forEach(issue => {
    const color = COLORS[issue.severity] || '#94a3b8';
    const rects = [];

    if (issue.type === 'sibling_overlap') {
      rects.push({ r: issue.element_a.rect, label: issue.id + 'a' });
      rects.push({ r: issue.element_b.rect, label: issue.id + 'b' });
    } else if (issue.element && issue.element.rect) {
      rects.push({ r: issue.element.rect, label: String(issue.id) });
    } else if (issue.element) {
      // collapsed_container has no rect (height=0) — show a thin bar at top of parent
      return;
    }

    rects.forEach(({ r, label }) => {
      if (!r || r.width === 0) return;

      const box = document.createElement('div');
      const h = Math.max(r.height, 2); // ensure collapsed elements get a visible bar
      box.style.cssText = [
        'position:absolute',
        'top:'    + r.top    + 'px',
        'left:'   + r.left   + 'px',
        'width:'  + r.width  + 'px',
        'height:' + h        + 'px',
        'border:2px solid ' + color,
        'box-sizing:border-box',
        'pointer-events:none',
      ].join(';');

      const badge = document.createElement('span');
      badge.textContent = label;
      badge.style.cssText = [
        'position:absolute', 'top:-1px', 'left:-1px',
        'background:' + color,
        'color:white',
        'font:bold 11px/18px monospace',
        'padding:0 4px',
        'border-radius:2px',
        'white-space:nowrap',
      ].join(';');
      box.appendChild(badge);
      overlay.appendChild(box);
    });
  });
}
"""


# ── Python orchestration ──────────────────────────────────────────────────

def _severity_order(issue: dict) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(issue.get("severity", "low"), 3)


def _compact_issues(issues: list[dict], max_issues: int = 30) -> list[dict]:
    """Strip verbose data from issues and cap total count for payload size."""
    compact = []
    for issue in issues[:max_issues]:
        entry = {
            "id": issue.get("id"),
            "type": issue.get("type"),
            "severity": issue.get("severity"),
            "intentionality_score": issue.get("intentionality_score"),
            "note": issue.get("note", "")[:200],
        }
        # Include section_index for richness issues
        if "section_index" in issue:
            entry["section_index"] = issue["section_index"]
        if "richness_score" in issue:
            entry["richness_score"] = issue["richness_score"]
        if "signals_present" in issue:
            entry["signals_present"] = issue["signals_present"]
        compact.append(entry)
    if len(issues) > max_issues:
        compact.append({
            "note": f"... and {len(issues) - max_issues} more issues (showing top {max_issues} by severity)"
        })
    return compact


def _deduplicate(issues: list[dict]) -> list[dict]:
    """Remove near-duplicate issues (same type + same selector pair)."""
    seen: set[frozenset] = set()
    unique: list[dict] = []
    for issue in issues:
        if issue["type"] == "sibling_overlap":
            key = frozenset({
                issue["type"],
                issue["element_a"]["selector"],
                issue["element_b"]["selector"],
            })
        elif "element" in issue and isinstance(issue["element"], dict):
            key = frozenset({issue["type"], issue["element"].get("selector", "")})
        else:
            key = frozenset({issue["type"], str(issue.get("id"))})

        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def check_layout(
    url: str,
    viewport_width: int = 1440,
    viewport_height: int = 900,
    wait_ms: int = 2500,
) -> dict[str, Any]:
    """Navigate to url, detect layout issues, annotate, screenshot.

    Args:
        url: Page to check. Must be reachable from this machine (e.g. http://localhost:3000).
        viewport_width: Desktop width (default 1440). Run again with 390 for mobile.
        viewport_height: Viewport height (default 900).
        wait_ms: Milliseconds to wait after load before detecting (allows animations to settle).

    Returns dict with:
        issues     — list of structured issues sorted by severity
        screenshot_path — path to annotated screenshot (read it with your Read/vision tool)
        summary    — plain-text summary for quick triage
        stats      — counts by type and severity
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "error": "playwright not installed. Run: pip install playwright && playwright install chromium",
            "issues": [],
            "screenshot_path": None,
        }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})

        try:
            page.goto(url, wait_until="networkidle", timeout=30_000)
        except Exception:
            # Fallback: domcontentloaded is enough for static Next.js exports
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Wait for framer-motion and fonts to settle
        page.wait_for_timeout(wait_ms)

        # Scroll to top so getBoundingClientRect() == page-absolute at Y=0
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(100)

        # Run layout detection
        raw_issues: list[dict] = page.evaluate(_DETECTION_JS)

        # Run visual richness detection
        richness_issues: list[dict] = page.evaluate(_RICHNESS_JS)
        raw_issues.extend(richness_issues)

        # Deduplicate and sort
        issues = _deduplicate(raw_issues)
        issues.sort(key=_severity_order)

        # Re-number after dedup
        for idx, issue in enumerate(issues, 1):
            issue["id"] = idx

        # Inject visual annotations
        page.evaluate(_ANNOTATE_JS, issues)
        page.wait_for_timeout(100)

        # Full-page screenshot with annotations
        tmp_dir = Path(tempfile.mkdtemp(prefix="superpower_layout_"))
        host_slug = url.replace("://", "_").replace("/", "_").replace(":", "_")[:40]
        screenshot_path = tmp_dir / f"layout_check_{host_slug}_{viewport_width}w.png"
        page.screenshot(path=str(screenshot_path), full_page=True)

        browser.close()

    # Build summary
    high   = [i for i in issues if i.get("severity") == "high"]
    medium = [i for i in issues if i.get("severity") == "medium"]
    low    = [i for i in issues if i.get("severity") == "low"]

    by_type: dict[str, int] = {}
    for issue in issues:
        by_type[issue["type"]] = by_type.get(issue["type"], 0) + 1

    # Separate layout issues from richness issues for clearer reporting
    layout_issues = [i for i in issues if i["type"] not in ("low_visual_richness", "page_visual_monotony")]
    richness_issues_found = [i for i in issues if i["type"] in ("low_visual_richness", "page_visual_monotony")]

    summary_lines = [
        f"Layout check: {url} @ {viewport_width}px",
        f"Found {len(issues)} issue(s): {len(high)} high, {len(medium)} medium, {len(low)} low",
    ]
    if issues:
        summary_lines.append("Issues by type: " + ", ".join(f"{t}×{n}" for t, n in by_type.items()))
        summary_lines.append("")

        if layout_issues:
            summary_lines.append("── LAYOUT ISSUES ──")
        for issue in layout_issues:
            itype = issue["type"].replace("_", " ")
            sev   = issue.get("severity", "?").upper()
            note  = issue.get("note", "")
            if issue["type"] == "sibling_overlap":
                a = issue["element_a"]["selector"]
                b = issue["element_b"]["selector"]
                summary_lines.append(f"[{sev}] #{issue['id']} {itype}: {a!r} overlaps {b!r} — {note}")
            elif "element" in issue and isinstance(issue["element"], dict):
                sel = issue["element"].get("selector", "?")
                summary_lines.append(f"[{sev}] #{issue['id']} {itype}: {sel!r} — {note}")

        if richness_issues_found:
            summary_lines.append("")
            summary_lines.append("── VISUAL RICHNESS ISSUES ──")
            summary_lines.append(
                "These sections look template-grade — they lack the visual depth "
                "and surface treatments that award-winning sites use. Fix these "
                "to match your reference quality."
            )
            for issue in richness_issues_found:
                sev = issue.get("severity", "?").upper()
                note = issue.get("note", "")
                summary_lines.append(f"[{sev}] #{issue['id']} — {note}")
    else:
        summary_lines.append("No layout or visual richness issues detected.")

    return {
        "url": url,
        "viewport_width": viewport_width,
        "issues": _compact_issues(issues),
        "screenshot_path": str(screenshot_path),
        "summary": "\n".join(summary_lines),
        "stats": {
            "total": len(issues),
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
            "by_type": by_type,
        },
    }


def _is_local_url(url: str) -> bool:
    return any(h in url for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"))


if __name__ == "__main__":
    """CLI entrypoint so the agent can run this locally via Bash.

    Usage:
        python -m src.layout_checker <url> [viewport_width]

    Prints a JSON result to stdout. The agent reads screenshot_path from the
    result and opens it with its Read tool to see the annotated screenshot.
    """
    import sys
    import json as _json

    if len(sys.argv) < 2:
        print(_json.dumps({"error": "Usage: python -m src.layout_checker <url> [viewport_width]"}))
        sys.exit(1)

    _url = sys.argv[1]
    _width = int(sys.argv[2]) if len(sys.argv) > 2 else 1440
    result = check_layout(url=_url, viewport_width=_width)
    print(_json.dumps(result))
