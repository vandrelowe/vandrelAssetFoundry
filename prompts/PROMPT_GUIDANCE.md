> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or the provider pipeline contract, the higher
> authority wins.

# Asset generation prompt guidance

## Prompt-set status

- **Active reference-first scene dressing:** `prehistoric_*.txt`,
  `granite_bedrock_outcrop_v2.txt`,
  `rounded_rock_outcrop_excavation_aware.txt`, and
  `caveman_ungulate_carcass_001.txt`. These are creative inputs only; they do
  not authorize a provider call, spend, candidate creation, approval, or
  publication.
- **Preservation-only creature concepts:** `pleistocene_*.txt`. These files
  retain paused creative work and must not be used as active provider inputs
  until the user explicitly reopens the creature corridor.

The status labels live here rather than inside prompt bodies so a prompt file
can remain a clean generation input if its category is later authorized.

## Reference-first scene-dressing workflow

For new scene dressing, these prompts first describe a reference image to be
generated outside Meshy and reviewed by the user. Do not submit the text
directly to Meshy merely because it fits the Text-to-3D limit. After the user
accepts the concept image, retain that exact image with the candidate and use
Meshy Image-to-3D with the appropriate native-remesh budget.

Reference concepts should show one isolated asset, the whole silhouette, a
plain or transparent contrasting background, even neutral lighting, and a
three-quarter view that exposes the top, sides, and ground-contact shape. Avoid
cast shadows that hide the base, surrounding scenery, terrain tiles, labels,
scale-reference objects, depth of field, and cropped geometry. The image must
make thin parts and overlapping forms legible enough to reject a bad design
before spending provider credits.

Meshy Text-to-3D is reserved for a specifically authorized provider experiment.
It is not the default iteration path for these prompt examples.

## Excavation classes

Choose one class for every asset intended to sit on, emerge from, or intersect
terrain. This is generation intent, not Vandrel gameplay classification.

### `surface_clutter`

Use for loose bones, sticks, leaf litter, small pebbles, ash piles, dropped
tools, flint chips, and loose hide scraps.

Required wording:

```text
surface-only object; no below-ground continuation required
```

### `embedded`

Use for medium rocks, stone slabs, small bushes, posts, totems, fire rings,
cairns, spear bundles, racks, and similar objects that visibly penetrate soil.

Required wording:

```text
includes a visible ground-intersection zone and a simple buried continuation below the soil line
```

### `excavation_aware`

Use for large trees, major root systems, rock outcrops, bedrock slabs, animal
dens, half-buried skulls, giant rib cages, and large stumps.

Required wording:

```text
designed for a game with diggable terrain, with above-ground form, visible soil-line transition, and believable below-ground continuation
```

For both `embedded` and `excavation_aware`, also include:

```text
does not terminate flat at the ground plane; not just a surface prop
```

Negative guidance:

```text
no flat cut-off bottom, no paper-thin base, no floating object, no object simply sitting on top of a flat plane, no hollow underside
```

## Asset-specific continuation

- Trees: full exposed root flare at the soil line, with major roots continuing
  below the ground line.
- Rocks and outcrops: larger buried rock mass continuing below the visible soil
  line, like bedrock emerging from the ground.
- Bushes and stumps: root crown and simple buried root mass below the soil line.
- Dens and burrows: dark opening with tunnel geometry continuing into the dirt
  bank.
- Posts, totems, and racks: lower ends visibly driven into or buried below the
  soil.

## Suggested defaults

| Asset kind | Excavation class |
|---|---|
| tree | `excavation_aware` |
| large rock / rock outcrop / flat bedrock slab | `excavation_aware` |
| bush | `embedded` |
| stump | `excavation_aware` |
| fallen log | `embedded` |
| ground cover | `surface_clutter` |
| loose bones / bone scatter | `surface_clutter` |
| giant skull / rib cage | `excavation_aware` |
| animal den | `excavation_aware` |
| stone cairn / totem / spear bundle / fire ring | `embedded` |
| ash pile | `surface_clutter` |

If a prompt is exceptionally authorized for Meshy Text-to-3D, it must fit the
provider's 600-character limit. Prefer concrete geometry language over
repeating style adjectives.

## Rounded rock outcrop example

See `prompts/examples/rounded_rock_outcrop_excavation_aware.txt`. It intentionally
describes rock geometry below grade without baking a soil disk into the asset.
