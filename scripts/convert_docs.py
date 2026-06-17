#%%
"""
Convert Markdown documentation files to DOCX using Pandoc.

- Fixes encoding mojibake (UTF-8 bytes saved as cp1252) in source files
- Renders Mermaid code blocks to PNG and inserts them as images
- No table of contents or section numbers by default

Usage -- convert all .md files in a folder individually:
    python scripts/convert_docs.py

Usage -- combine specific files into one document:
    python scripts/convert_docs.py --combine

Requirements:
    Pandoc:      winget install JohnMacFarlane.Pandoc
    Mermaid CLI: npm install -g @mermaid-js/mermaid-cli
"""

#%%
from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path


#%%
PANDOC_EXE = "pandoc"
MMDC_EXE = "mmdc.cmd" if platform.system() == "Windows" else "mmdc"


#%%
def pandoc_available() -> bool:
    try:
        subprocess.run([PANDOC_EXE, "--version"], check=True, capture_output=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def mmdc_available() -> bool:
    try:
        subprocess.run([MMDC_EXE, "--version"], check=True, capture_output=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


# All non-ASCII characters that map to a single cp1252 byte.
# cp1252 0x80-0x9F map to characters outside U+0080-U+00FF (e.g. em dash U+2014 = 0x97),
# so a simple [\x80-\xFF] regex misses them — we need this full set.
_CP1252_CHARS: frozenset[str] = frozenset(
    c
    for b in range(0x80, 0x100)
    if (c := bytes([b]).decode("cp1252", errors="ignore"))
)


def _fix_mojibake(text: str) -> str:
    """
    Fix mojibake where UTF-8 bytes were decoded as cp1252 and re-saved.
    Scans for runs of cp1252-encodable characters and tries to reverse the
    encoding. Handles e.g. Ã— -> ×, â€" -> —, â†' -> ->, âˆ' -> −.
    """
    result: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c not in _CP1252_CHARS:
            result.append(c)
            i += 1
            continue
        # Try longest sequence first (4 bytes covers all UTF-8 codepoints)
        fixed = False
        for length in range(min(4, n - i), 1, -1):
            chunk = text[i : i + length]
            if not all(ch in _CP1252_CHARS for ch in chunk):
                continue
            try:
                decoded = chunk.encode("cp1252").decode("utf-8")
                result.append(decoded)
                i += length
                fixed = True
                break
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
        if not fixed:
            result.append(c)
            i += 1
    return "".join(result)


def _render_mermaid_blocks(content: str, source_stem: str, image_dir: Path) -> str:
    """Replace ```mermaid...``` fenced blocks with PNG image references."""
    if "```mermaid" not in content:
        return content

    if not mmdc_available():
        print(
            "  Warning: mmdc not found -- Mermaid blocks left as code.\n"
            "  Install with: npm install -g @mermaid-js/mermaid-cli"
        )
        return content

    image_dir.mkdir(parents=True, exist_ok=True)
    block_pattern = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
    idx = 0

    def replace_block(m: re.Match) -> str:
        nonlocal idx
        diagram_src = m.group(1)
        img_path = image_dir / f"{source_stem}_mermaid_{idx}.png"
        idx += 1

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".mmd", delete=False
        ) as f:
            f.write(diagram_src)
            mmd_path = Path(f.name)

        result = subprocess.run(
            [MMDC_EXE, "-i", str(mmd_path), "-o", str(img_path), "--backgroundColor", "white"],
            capture_output=True,
            text=True,
        )
        mmd_path.unlink(missing_ok=True)

        if result.returncode != 0:
            print(f"  Warning: mmdc failed for {source_stem} block {idx}: {result.stderr.strip()}")
            return m.group(0)

        print(f"    Mermaid diagram -> {img_path.name}")
        return f"![]({img_path})"

    return block_pattern.sub(replace_block, content)


def _normalise_md(path: Path, mermaid_image_dir: Path) -> tuple[Path, list[Path]]:
    """
    Read an .md file, fix mojibake encoding, render Mermaid blocks.
    Returns (processed_path, temp_files_to_delete).
    Returns the original path unchanged if no processing was needed.
    """
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = path.read_text(encoding="cp1252")

    fixed = _fix_mojibake(content)
    fixed = _render_mermaid_blocks(fixed, path.stem, mermaid_image_dir)

    if fixed == content:
        return path, []

    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".md", delete=False
    )
    tmp.write(fixed)
    tmp.close()
    return Path(tmp.name), [Path(tmp.name)]


def convert_md_to_docx(
    md_paths: list[Path],
    output_path: Path,
    resource_paths: list[Path],
    mermaid_image_dir: Path,
    reference_doc: Path | None = None,
    add_toc: bool = False,
    number_sections: bool = False,
) -> bool:
    """Convert one or more Markdown files to a single DOCX using Pandoc."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    resource_path_arg = ";".join(str(p) for p in resource_paths)

    normalised: list[Path] = []
    temp_files: list[Path] = []
    for p in md_paths:
        norm_path, tmps = _normalise_md(p, mermaid_image_dir)
        normalised.append(norm_path)
        temp_files.extend(tmps)

    cmd = [
        PANDOC_EXE,
        *[str(p) for p in normalised],
        "-o", str(output_path),
        f"--resource-path={resource_path_arg}",
        # Suppress auto-captioning of standalone images
        "--from=markdown-implicit_figures",
    ]

    if add_toc:
        cmd.append("--toc")

    if number_sections:
        cmd.append("--number-sections")

    if reference_doc and reference_doc.exists():
        cmd += ["--reference-doc", str(reference_doc)]

    label = output_path.name
    input_label = ", ".join(p.name for p in md_paths)
    print(f"  {input_label}  ->  {label}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    for tmp in temp_files:
        tmp.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def convert_folder_individually(
    docs_dir: Path,
    output_dir: Path,
    resource_paths: list[Path],
    mermaid_image_dir: Path,
    reference_doc: Path | None,
    glob: str = "*.md",
    exclude_dirs: list[str] | None = None,
) -> list[Path]:
    """Convert each .md file in docs_dir to its own DOCX."""
    exclude_dirs = exclude_dirs or []
    md_files = [
        p for p in sorted(docs_dir.rglob(glob))
        if not any(part in exclude_dirs for part in p.parts)
    ]

    if not md_files:
        print(f"No Markdown files found in {docs_dir}")
        return []

    outputs = []
    for md_path in md_files:
        output_path = output_dir / f"{md_path.stem}.docx"
        ok = convert_md_to_docx(
            md_paths=[md_path],
            output_path=output_path,
            resource_paths=resource_paths,
            mermaid_image_dir=mermaid_image_dir,
            reference_doc=reference_doc,
        )
        if ok:
            outputs.append(output_path)

    return outputs


def convert_combined(
    md_files: list[Path],
    output_path: Path,
    resource_paths: list[Path],
    mermaid_image_dir: Path,
    reference_doc: Path | None,
) -> bool:
    """Combine a list of Markdown files into one DOCX."""
    return convert_md_to_docx(
        md_paths=md_files,
        output_path=output_path,
        resource_paths=resource_paths,
        mermaid_image_dir=mermaid_image_dir,
        reference_doc=reference_doc,
    )


#%%
# ---------------------------------------------------------------------------
# Repo-specific configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent

DOCS_DIR = REPO_ROOT / "docs" / "new model"

OUTPUT_DIR = REPO_ROOT / "docs" / "docx"

MERMAID_IMAGE_DIR = OUTPUT_DIR / "mermaid"

# Directories inside DOCS_DIR to skip (e.g. archive folders)
EXCLUDE_DIRS = ["archive"]

# Extra image search paths beyond DOCS_DIR itself
EXTRA_IMAGE_DIRS: list[Path] = [
    DOCS_DIR / "images",
    MERMAID_IMAGE_DIR,
]

# Optional: path to a .docx reference template for custom styles.
# Create one with: pandoc --print-default-data-file reference.docx > reference.docx
# Then edit it in Word to set fonts/colours/heading styles.
REFERENCE_DOC: Path | None = REPO_ROOT / "docs" / "reference.docx"

# Files to combine (in order) when --combine flag is used.
COMBINED_OUTPUT_STEM = "Road Transport Model Documentation"
COMBINED_FILES: list[Path] = [
    DOCS_DIR / "road_transport_model_overview.md",
    DOCS_DIR / "road_transport_model_methodology.md",
    DOCS_DIR / "road_transport_model_modeller_guide.md",
]


#%%
def build_resource_paths() -> list[Path]:
    return [REPO_ROOT, DOCS_DIR, *EXTRA_IMAGE_DIRS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert docs to DOCX")
    parser.add_argument(
        "--combine",
        action="store_true",
        help="Combine COMBINED_FILES into a single DOCX instead of per-file output",
    )
    args = parser.parse_args()

    if not pandoc_available():
        print("Pandoc not found. Install it with: winget install JohnMacFarlane.Pandoc")
        sys.exit(1)

    reference_doc = REFERENCE_DOC if (REFERENCE_DOC and REFERENCE_DOC.exists()) else None
    if REFERENCE_DOC and not REFERENCE_DOC.exists():
        print(f"Note: reference.docx not found at {REFERENCE_DOC} - using Pandoc defaults.")
        print("      To customise styles: pandoc --print-default-data-file reference.docx > docs/reference.docx")
        print()

    resource_paths = build_resource_paths()

    if args.combine:
        missing = [p for p in COMBINED_FILES if not p.exists()]
        if missing:
            print("Missing files:")
            for p in missing:
                print(f"  {p}")
            sys.exit(1)

        output_path = OUTPUT_DIR / f"{COMBINED_OUTPUT_STEM}.docx"
        print(f"Combining {len(COMBINED_FILES)} files into {output_path.name} ...")
        ok = convert_combined(
            md_files=COMBINED_FILES,
            output_path=output_path,
            resource_paths=resource_paths,
            mermaid_image_dir=MERMAID_IMAGE_DIR,
            reference_doc=reference_doc,
        )
        if ok:
            print(f"Done: {output_path}")
    else:
        print(f"Converting all .md files in {DOCS_DIR} ...")
        outputs = convert_folder_individually(
            docs_dir=DOCS_DIR,
            output_dir=OUTPUT_DIR,
            resource_paths=resource_paths,
            mermaid_image_dir=MERMAID_IMAGE_DIR,
            reference_doc=reference_doc,
            exclude_dirs=EXCLUDE_DIRS,
        )
        print(f"\nDone: {len(outputs)} file(s) written to {OUTPUT_DIR}")


#%%
if __name__ == "__main__":
    main()
