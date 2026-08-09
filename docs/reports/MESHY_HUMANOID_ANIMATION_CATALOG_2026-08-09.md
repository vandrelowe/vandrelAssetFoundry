> Reference only. If this document conflicts with Foundry governance,
> architecture authority, or a corridor contract, the higher authority wins.

# Meshy humanoid animation catalog and acquisition decision

**Date:** 2026-08-09
**Scope:** Current Meshy biped catalog, Caveman rig compatibility, and bounded
acquisition decision
**Provider writes or spend:** None; authenticated `GET /openapi/v1/balance`
only
**Candidate, Library, release, Vandrel, Git, or existing-asset mutation:** None

## Decision

Meshy's current public biped catalog contains **678 actions**, not about 500.
It has useful approximations for a standing hand-to-mouth action, a low cutting
swing, fear, and non-boxing weapon attacks, but it does **not** contain an action
named or previewed as an exact eating/chewing loop or an exact kneeling
butchering/dressing loop.

The smallest reusable technical path is to retain the current Caveman mesh,
skin, bind matrices, and 33-bone Mixamo-compatible armature, then semantically
retarget selected Meshy core-body motion into that target rest space. Direct
animation graft is invalid: the observed Meshy biped has 24 joints and a
different spine hierarchy, while the current Caveman FBX has 33 bones including
index-finger and terminal bones.

No animation was acquired in this pass. Meshy's current web-app pricing lists
Animate as 0 credits per clip, but its current API pricing lists Animation as 3
credits per call. The configured API credential authenticated successfully and
the balance endpoint returned 1329 credits, but the controllable browser
session still displayed `Log In`, so the account plan, selected output license,
and zero-credit web-app submission could not be verified safely. A paid API
submission is outside this task's authority.

## Catalog record

The complete provider catalog is preserved separately from any acquired bytes:

- Source: [Meshy Animation Library Reference](https://docs.meshy.ai/en/api/animation-library)
- Scope: `biped`
- Rows: 678 unique action IDs
- ID range: 0-696, with 19 documented gaps
- Canonical compact `actions` array SHA-256:
  `f6548806e3421531a9aa518524d1c2e3fd67b1ba58d93968745c6f80b754808b`
- Snapshot:
  [`evidence/meshy-humanoid-animation-catalog/animation-library-2026-08-09.json`](evidence/meshy-humanoid-animation-catalog/animation-library-2026-08-09.json)

Each snapshot row binds the exact action ID, provider name, category,
subcategory, and provider preview GIF URL. The catalog does not expose a
downloadable source package or task identity. Meshy's Animation API creates a
new task from a successful rigging task plus an action ID; the resulting task
identity and output URLs exist only after submission.

## Acquisition and custody boundary

Current official provider surfaces disagree by channel, not by observation:

- [Web-app Pricing & Credits](https://docs.meshy.ai/en/webapp/pricing) lists
  Rigging and Animate at 0 credits. It states that paid-plan outputs support
  private/commercial use and free-plan outputs use CC BY 4.0 with attribution.
- [API Pricing](https://docs.meshy.ai/en/api/pricing) lists Auto-Rigging at 5
  credits and Animation at 3 credits per call.
- [Animation API](https://docs.meshy.ai/en/api/animation) requires a successful
  `rig_task_id` and `action_id`, and returns task-scoped GLB/FBX outputs. Its
  current example records `consumed_credits: 3`.
- [Meshy Terms of Service](https://www.meshy.ai/terms-of-use), last updated
  2026-03-07, classify animations and character rigs as Service Assets. The
  service-asset license is limited to use incorporated into and necessary to
  exploit Customer Output. Free-plan output is CC BY 4.0; paid-plan output may
  be private under the account terms.

Therefore a new intake must preserve, before download: account/channel, plan
and selected license shown for that output, rig task ID, animation task ID,
action ID/name, creation response including `consumed_credits`, output URL
identity without its expiring query secret, downloaded file hash/size/format,
and the exact source rig artifact. Public catalog rows alone are not acquisition
custody.

## Decision table

| Need | Provider action | Semantic fit from provider preview | Rig compatibility | Acquisition status/cost | License/custody status | Recommendation and exact next action |
| --- | --- | --- | --- | --- | --- | --- |
| Standing raw-food eating | `342` `Stand_and_Drink` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Stand_and_Drink.gif)) | Medium. Repeated hand-to-mouth path is useful, but the hand is posed for a cup and there is no visible chewing. | Retarget required; core arms/spine/head map, target index bones remain at target defaults. | Not acquired. Web app documents 0 credits; API costs 3 credits. | Catalog identity captured; no task/output custody or account-license selection yet. | First acquisition candidate. Submit only through a visibly authenticated web-app session showing 0 credits and the intended license; capture task/output metadata before download. |
| Crouched/seated raw-food eating | `343` `Sit_and_Drink` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Sit_and_Drink.gif)) | Low-medium. Hand-to-mouth repeats, but the wide seated posture is not the requested crouch and still reads as drinking. | Retarget required; contact and hip-height review mandatory. | Not acquired; same channel split as action 342. | Catalog only. | Keep as fallback/posture reference, not the primary eating solution. |
| Active carcass cutting | `99` `Reaping_Swing` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Reaping_Swing.gif)) | Medium. Preview shows a low, active cutting sweep, but not kneeling and not carcass dressing. | Retarget required; two-hand/tool contact and root displacement need validation. | Not acquired; web app 0/API 3. | Catalog only. | Best existing butchery prototype. Acquire after action 342 only if the authenticated web-app cost is explicitly 0; test as a looping low cut against a carcass proxy. |
| Kneeling butchery posture | `165` `Kneeling_Reload` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Kneeling_Reload.gif)) | Low as an action, medium as posture reference. It kneels but the hands perform a reload, not cutting. | Retarget required; knee/ground contact must be re-solved for the target proportions. | Not acquired; web app 0/API 3. | Catalog only. | Do not ship as butchery. Use only if a later Foundry composition corridor is approved to combine posture and authored hand work. |
| Kneeling transition | `365` `Kneel_on_One_Knee_and_Stand` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Kneel_on_One_Knee_and_Stand.gif)) | Medium for entering/exiting work; no cutting loop. | Retarget required. | Not acquired; web app 0/API 3. | Catalog only. | Optional transition around a future real butchery loop, not a substitute for it. |
| Fear/cower | `356` `Sit_Hands_on_Head_Lean_Back` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Sit_Hands_on_Head_Lean_Back.gif)) | Medium-high fear silhouette with hands protecting the head; appears transitional rather than a clean idle loop. | Retarget required; target hands need pose/contact review. | Not acquired; web app 0/API 3. | Catalog only. | Best cower-like candidate in the catalog. Acquire for loopability inspection after the two primary needs. |
| Fear/help | `294` `Wave_for_Help_2` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Wave_for_Help_2.gif)) | Low for cower; readable distress but upright and gestural. | Retarget required. | Not acquired; web app 0/API 3. | Catalog only. | Secondary distress reaction, not cower. |
| Non-boxing hunting strike | `240` `Thrust_Slash` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Thrust_Slash.gif)) | High for a spear/knife-like committed attack; not suitable for unarmed combat. | Retarget required; prop grip and attack-event timing need validation. | Not acquired; web app 0/API 3. | Catalog only. | Primary non-boxing hunting-strike candidate for a thrusting weapon. |
| Non-boxing chopping strike | `237` `Charged_Axe_Chop` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Charged_Axe_Chop.gif)) | High for a heavy primitive chopping weapon; too committed for a generic light strike. | Retarget required; both-hand alignment and root lunge need validation. | Not acquired; web app 0/API 3. | Catalog only. | Use when the gameplay weapon is axe/club-like; otherwise prefer action 240. |
| Existing useful motion | `224` `Archery_Shot` ([preview](https://cdn.meshy.ai/webapp-assets/feature-demo/animation/preview/biped/Archery_Shot.gif)) | Already represented in the local Meshy structural reference package. | Existing observed 24-joint clip; still requires the same retarget corridor for Caveman. | Existing local external package, not newly acquired. | Local hash exists but no provider task identity; insufficient as new provider custody. | Do not reacquire during this outcome. Use only as a regression fixture for the retarget corridor. |

## Exact rig comparison

The reproducible comparison record is
[`evidence/meshy-humanoid-animation-catalog/rig-compatibility-2026-08-09.json`](evidence/meshy-humanoid-animation-catalog/rig-compatibility-2026-08-09.json).

The current Caveman target inspected in Blender 5.2.0 LTS is one armature with
33 bones and two mesh objects. Its file is:

`C:/Dev/Vandrel/mods/CavemanMod/assets/raw/meshy_cavemen/mixamo_rigged/Male Cave Adult Athletic.fbx`

SHA-256:
`af5bf76b282367654519236da2b1b1c181be8a6ba986da3d0702b57b36c405ef`

The existing Meshy biped structural reference is one skin with 24 joints and 14
clips. Its inspected GLB SHA-256 is
`1a084a5cee71bd28c3f1c20e8582b9d513c7198626b0c10f35f28ffb9e25d8b3`.
That package has no provider task identity, so it is compatibility evidence,
not custody evidence for any new catalog action.

## Minimal reusable Foundry corridor

1. Intake the exact Meshy rig output and selected animation task output as
   immutable provider artifacts with task/action/license/cost evidence.
2. Inspect source and target independently: one skin/armature, finite rest
   transforms, required hips/spine/head/arm/leg chains, nonempty animation, and
   explicit unmapped helpers.
3. Map normalized semantic roles rather than indices. The Meshy spine chain is
   `Hips -> Spine02 -> Spine01 -> Spine`, whereas the Caveman chain is
   `Hips -> Spine -> Spine1 -> Spine2`; names alone are unsafe.
4. Bake source pose deltas into the target rest space with explicit unit/height
   scale and root-motion policy. Preserve the target mesh, skin, inverse bind
   matrices, hierarchy, and target-only index/end bones.
5. Validate every output hash with continuous/sampled lateral playback,
   hand-to-mouth or tool-contact metrics, foot/knee ground contact, root drift,
   nonfinite-transform rejection, and deformation bounds.

This is a processing/custody capability only. Semantic gameplay registration
for eating, butchery, fear, or hunting remains outside Foundry.

## Acquired bytes

**None.** No Meshy animation task was created, no credit was spent, no provider
terms were accepted, and no file was downloaded. Catalog evidence and local
read-only rig observations are intentionally separate from acquisition custody.

## Next authorized action

Sign in within the controllable Meshy workspace tab and confirm that the
account shows the intended output license and a 0-credit Animate submission.
Then acquire, in order, actions `342` and `99`, capturing task/output evidence
before download. If Meshy shows any nonzero cost or a new terms prompt, stop for
a separate decision. The exact kneeling butchery loop remains a content gap even
after those two acquisitions and will need either a different entitled source
or separately approved motion authoring/composition.
