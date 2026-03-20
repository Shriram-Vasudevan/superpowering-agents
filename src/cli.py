"""CLI interface for the design-reference RAG pipeline."""

from __future__ import annotations

import argparse
import json
import sys

from src.generation import generate_code
from src.intent import extract_intent
from src.pipeline import build_context_payload, build_context_system_prompt
from src.retrieval import retrieve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="superpowering-agents",
        description="Generate Next.js components from design references using RAG + Claude vision",
    )
    parser.add_argument("prompt", help="Description of the component to generate")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    parser.add_argument("--dry-run", action="store_true", help="Run retrieval only, skip generation")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print status messages to stderr")
    parser.add_argument("--top-k", type=int, default=5, help="Number of references to retrieve (default: 5)")
    parser.add_argument("--page-type", help="Override detected page type")
    parser.add_argument("--industry", help="Override detected industry")
    parser.add_argument("--no-vector", action="store_true", help="Skip vector search, use metadata filter only")
    parser.add_argument("--context", action="store_true", help="Output full context payload as JSON (skip generation)")
    return parser


def run(args: argparse.Namespace) -> None:
    # Step 1: Intent extraction
    intent = extract_intent(args.prompt, page_type_override=args.page_type, industry_override=args.industry)
    if args.verbose:
        print(f"Intent: page_type={intent.page_type}, industry={intent.industry}, "
              f"color={intent.color_preference}, style={intent.style_keywords}", file=sys.stderr)

    # Step 2: Retrieval
    results = retrieve(
        args.prompt,
        intent,
        top_k=args.top_k,
        no_vector=args.no_vector,
        verbose=args.verbose,
    )

    if not results:
        print("No matching references found.", file=sys.stderr)
        sys.exit(1)

    # Context mode: output full context payload as JSON and exit
    if args.context:
        payload = build_context_payload(args.prompt, intent, results)
        print(json.dumps(payload.model_dump(), indent=2))
        return

    # Dry run: print results and exit
    if args.dry_run:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Retrieved {len(results)} references:", file=sys.stderr)
        for i, r in enumerate(results, 1):
            print(f"\n  [{i}] {r.domain}", file=sys.stderr)
            print(f"      Similarity: {r.similarity:.4f}", file=sys.stderr)
            print(f"      Page type:  {r.descriptor.get('page_type')}", file=sys.stderr)
            print(f"      Industry:   {r.descriptor.get('industry')}", file=sys.stderr)
            print(f"      Style:      {r.descriptor.get('visual_style')}", file=sys.stderr)
            print(f"      Color:      {r.descriptor.get('color_mode')}", file=sys.stderr)
            print(f"      Quality:    {r.descriptor.get('quality_score')}", file=sys.stderr)
            print(f"      Screenshot: {r.screenshot_path}", file=sys.stderr)
        print(f"\n{'='*60}", file=sys.stderr)
        return

    # Step 3: Generation
    if args.verbose:
        print("Generating code...", file=sys.stderr)

    compiled_system_prompt, _ = build_context_system_prompt(args.prompt, intent, results)
    code = generate_code(args.prompt, results, system_prompt=compiled_system_prompt, verbose=args.verbose)

    # Step 4: Output
    if args.output:
        with open(args.output, "w") as f:
            f.write(code + "\n")
        if args.verbose:
            print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(code)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run(args)
