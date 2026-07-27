import base64
import hashlib
import html
import os
from pathlib import Path

from vandrel_foundry.config import FoundryConfig
from vandrel_foundry.domain.errors import FoundryError
from vandrel_foundry.domain.manifest import AssetManifest
from vandrel_foundry.services.inspect_assets import discover_assets
from vandrel_foundry.storage.paths import contained_path

MAX_GALLERY_ASSETS = 1000
MAX_PREVIEW_BYTES = 10 * 1024 * 1024


def build_review_gallery(config: FoundryConfig) -> Path:
    manifests, warnings = discover_assets(config.foundry.workspace_root)
    if warnings:
        raise FoundryError(f"Review gallery requires valid manifests: {warnings[0]}")
    if len(manifests) > MAX_GALLERY_ASSETS:
        raise FoundryError(f"Review gallery exceeds {MAX_GALLERY_ASSETS} candidates.")
    destination = _next_destination(config.foundry.workspace_root)
    cards = "\n".join(_card(config, manifest) for manifest in manifests)
    document = _document(cards, len(manifests))
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise FoundryError(f"Could not write review gallery {destination}: {exc}") from exc
    return destination


def _card(config: FoundryConfig, manifest: AssetManifest) -> str:
    asset_root = config.foundry.workspace_root / "assets" / manifest.asset.asset_id
    previews = [artifact for artifact in manifest.artifacts if artifact.role == "local_preview"]
    image = "<div class='placeholder'>No local preview</div>"
    if previews:
        artifact = previews[-1]
        path = contained_path(asset_root, artifact.path)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise FoundryError(
                f"Could not read preview for {manifest.asset.asset_id}: {exc}"
            ) from exc
        if payload[:8] != b"\x89PNG\r\n\x1a\n":
            raise FoundryError(f"Recorded preview is not a PNG: {manifest.asset.asset_id}")
        if len(payload) > MAX_PREVIEW_BYTES:
            raise FoundryError(f"Recorded preview is too large: {manifest.asset.asset_id}")
        if (
            len(payload) != artifact.size_bytes
            or hashlib.sha256(payload).hexdigest() != artifact.sha256
        ):
            raise FoundryError(f"Recorded preview changed: {manifest.asset.asset_id}")
        encoded = base64.b64encode(payload).decode("ascii")
        image = f"<img src='data:image/png;base64,{encoded}' alt='Local preview'>"
    observed = manifest.quality.observed
    checks = "".join(
        f"<li class='{'pass' if check.get('passed') else 'fail'}'>"
        f"{html.escape(str(check.get('name', 'unnamed')))}</li>"
        for check in manifest.validation.checks
    )
    metrics = (
        f"{observed.get('triangle_count', '—')} triangles · "
        f"{observed.get('material_count', '—')} materials · "
        f"{observed.get('animation_count', '—')} animations"
    )
    search = html.escape(
        f"{manifest.asset.display_name} {manifest.asset.asset_id} {manifest.asset.lane}".casefold(),
        quote=True,
    )
    return (
        f"<article class='card' data-state='{html.escape(manifest.workflow.state.value, quote=True)}' "
        f"data-lane='{html.escape(manifest.asset.lane, quote=True)}' data-search='{search}'>"
        f"{image}<div class='body'><h2>{html.escape(manifest.asset.display_name)}</h2>"
        f"<code>{html.escape(manifest.asset.asset_id)}</code>"
        f"<p><span class='state'>{html.escape(manifest.workflow.state.value)}</span> "
        f"{html.escape(manifest.asset.lane)}</p><p>{html.escape(metrics)}</p>"
        f"<ul>{checks}</ul></div></article>"
    )


def _next_destination(workspace_root: Path) -> Path:
    root = workspace_root / "review_reports"
    number = 1
    while True:
        candidate = root / f"review-gallery-{number:03d}.html"
        if not candidate.exists():
            return candidate
        number += 1


def _document(cards: str, count: int) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vandrel Asset Foundry Review Gallery</title>
<style>
body{{margin:0;background:#11151c;color:#e8edf5;font:15px system-ui;padding:28px}}
header{{max-width:1200px;margin:auto auto 24px}} h1{{margin:0}} header p{{color:#9aa8ba}}
.controls{{display:flex;gap:10px;flex-wrap:wrap}} input,select{{background:#1b2330;color:#e8edf5;
border:1px solid #465670;border-radius:7px;padding:9px 11px}}
.grid{{max-width:1200px;margin:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}}
.card{{background:#1b2330;border:1px solid #344156;border-radius:12px;overflow:hidden}}
img,.placeholder{{width:100%;aspect-ratio:1;object-fit:contain;background:#080b10;display:grid;place-items:center}}
.placeholder{{color:#6f7d91}} .body{{padding:16px}} h2{{margin:0 0 6px;font-size:19px}}
code{{color:#95c8ff}} .state{{background:#30405a;padding:3px 8px;border-radius:999px}}
ul{{columns:2;padding-left:18px}} .pass{{color:#8ee6a4}} .fail{{color:#ff8e93}}
</style></head><body><header><h1>Review Gallery</h1>
<p>{count} candidates · offline snapshot · informational only; approval remains a CLI action.</p>
<div class="controls"><input id="search" aria-label="Search assets" placeholder="Search assets">
<select id="state" aria-label="Filter by state"><option value="">All states</option>
<option value="review">Review</option><option value="approved">Approved</option>
<option value="rejected">Rejected</option></select>
<select id="lane" aria-label="Filter by lane"><option value="">All lanes</option>
<option value="static_prop">Static prop</option><option value="humanoid">Humanoid</option>
<option value="environment_near">Environment near</option>
<option value="environment_distant">Environment distant</option>
<option value="creature">Creature</option></select></div>
</header><main class="grid">{cards}</main>
<script>
const controls=[document.querySelector('#search'),document.querySelector('#state'),
document.querySelector('#lane')]; function filterCards(){{
const q=controls[0].value.toLowerCase(),state=controls[1].value,lane=controls[2].value;
for(const card of document.querySelectorAll('.card')){{
card.hidden=!!((q&&!card.dataset.search.includes(q))||(state&&card.dataset.state!==state)||
(lane&&card.dataset.lane!==lane));}}}} controls.forEach(control=>control.addEventListener('input',filterCards));
</script></body></html>
"""
