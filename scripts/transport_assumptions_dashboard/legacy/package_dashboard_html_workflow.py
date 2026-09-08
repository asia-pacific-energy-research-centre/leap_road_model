#%%
"""Wrap dashboard fragments as easy-to-open local HTML files."""

from __future__ import annotations

import html
from pathlib import Path


def build_wrapper(fragment: str, title: str) -> str:
    """Create a local-file wrapper that permits downloads and dashboard navigation."""
    allowed_paths = [
        "../non_road_assumptions_dashboard/non_road_assumptions_dashboard_all_economies.html",
        "../international_transport_assumptions_dashboard/international_transport_assumptions_dashboard_all_economies.html",
        "../road_transport_assumptions_dashboard/road_transport_assumptions_dashboard_all_economies.html",
    ]
    listener = (
        "window.addEventListener('message',event=>{const allowed=new Set("
        + repr(allowed_paths)
        + ");if(event.data?.type==='transport-dashboard-navigation'&&allowed.has(event.data.path))"
        + "window.location.href=event.data.path;});"
    )
    iframe_reset = (
        '<style data-dashboard-document-reset>'
        'html{color-scheme:light dark}'
        'html,body{margin:0;min-height:100%;background:light-dark(#f4f7f6,#111a1c)}'
        '</style>'
    )
    escaped_fragment = html.escape(iframe_reset + fragment, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{html.escape(title)}</title>
<script>{listener}</script>
<style>:root{{color-scheme:light dark;background:light-dark(#f4f7f6,#111a1c)}}html,body{{margin:0;min-height:100%;background:inherit}}body{{box-sizing:border-box;padding:0}}iframe{{display:block;width:100%;height:100vh;margin:0;border:0;background:inherit}}</style>
</head>
<body>
<iframe sandbox="allow-scripts allow-downloads" referrerpolicy="no-referrer" title="{html.escape(title)}" srcdoc="{escaped_fragment}"></iframe>
</body>
</html>
"""


def write_wrapped_dashboard(fragment_path: Path, output_path: Path, title: str) -> None:
    """Read a fragment and write its standalone wrapper."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fragment = fragment_path.read_text(encoding="utf-8")
    output_path.write_text(build_wrapper(fragment, title), encoding="utf-8")


def normalize_legacy_wrapper(output_path: Path) -> None:
    """Apply full-bleed outer and iframe-document styles to a retained dashboard."""
    if not output_path.exists():
        return
    html_text = output_path.read_text(encoding="utf-8")
    old_style = "<style>:root{color-scheme:light dark;background:light-dark(rgb(255 255 255), rgb(24 24 24))}html,body{margin:0}body{box-sizing:border-box;padding:1rem;background:inherit}iframe{display:block;width:100%;height:calc(100vh - 2rem);margin:0 auto;border:0}</style>"
    new_style = "<style>:root{color-scheme:light dark;background:light-dark(#f4f7f6,#111a1c)}html,body{margin:0;min-height:100%;background:inherit}body{box-sizing:border-box;padding:0}iframe{display:block;width:100%;height:100vh;margin:0;border:0;background:inherit}</style>"
    html_text = html_text.replace(old_style, new_style)
    if "data-dashboard-document-reset" not in html_text:
        iframe_reset = html.escape(
            '<style data-dashboard-document-reset>'
            'html{color-scheme:light dark}'
            'html,body{margin:0;min-height:100%;background:light-dark(#f4f7f6,#111a1c)}'
            '</style>',
            quote=True,
        )
        html_text = html_text.replace('srcdoc="', f'srcdoc="{iframe_reset}', 1)
    output_path.write_text(html_text, encoding="utf-8")


def run_package_workflow(workflow_dir: Path, output_root: Path) -> None:
    """Regenerate the two fragment-based dashboard entry files."""
    write_wrapped_dashboard(
        workflow_dir / "all_economies_dashboard_fragment.html",
        output_root / "non_road_assumptions_dashboard" / "non_road_assumptions_dashboard_all_economies.html",
        "Domestic non-road assumptions dashboard",
    )
    write_wrapped_dashboard(
        workflow_dir / "international_transport_dashboard_fragment.html",
        output_root / "international_transport_assumptions_dashboard" / "international_transport_assumptions_dashboard_all_economies.html",
        "International transport assumptions dashboard",
    )
    normalize_legacy_wrapper(
        output_root / "non_road_assumptions_dashboard" / "non_road_assumptions_dashboard_russia_prc.html"
    )


# --- Frequently changed settings ---

WORKFLOW_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = WORKFLOW_DIR.parents[1] / "outputs"
# Packaging is orchestrated by build_transport_assumptions_dashboard.py.
RUN_PACKAGE_WORKFLOW = False


# --- Notebook-style run block ---

if RUN_PACKAGE_WORKFLOW:
    try:
        run_package_workflow(workflow_dir=WORKFLOW_DIR, output_root=OUTPUT_ROOT)
        print("Dashboard wrappers regenerated.")
    except Exception as error:
        print(f"Dashboard wrapper workflow failed: {type(error).__name__}: {error}")
        raise

#%%
