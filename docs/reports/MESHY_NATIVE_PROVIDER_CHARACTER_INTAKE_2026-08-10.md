> Reference only. If this report conflicts with Foundry governance or a
> corridor contract, the higher authority wins.

# Meshy-native Primal character intake: technical evidence

**Date:** 2026-08-10
**Scope:** two fresh, unreleased Foundry humanoid candidates
**Provider/network/spend:** none performed by Foundry
**Vandrel, Asset Library, approval, release, or publication:** none

## Decision

Both user-selected local Meshy native-biped ZIPs passed exact-root intake and
direct Blender inspection. Each preserves one Meshy 24-joint armature, one
skinned mesh, one material slot, two referenced images, its native bind
signature, and zero unweighted vertices. The supplied `Walking_withSkin` FBX
has the same skeleton and skin as its character FBX and a 1.033333-second
`walking_man` action. Both exact joint names and their in-joint hierarchies
match the current Meshy-native carrier canary.

This is a narrow compatibility result, not an animation transfer or adoption
decision. No canary action was retargeted, no semantic game identity was
assigned, and no approval, release, Library, or Vandrel write occurred.

## Exact source and provider observation

Provider identities and the unchanged account balance are user-observed
metadata, not recovered task responses. Foundry did not call Meshy, inspect
embedded licensing metadata, or download these files. `license_metadata` is
therefore exactly `not_inspected`.

| Candidate | ZIP SHA-256 | User-observed lineage | Root union |
| --- | --- | --- | --- |
| `meshy_native_primal_male_001` | `a951d30d742c556af2284d619a90c196e525934afced481c1b26671ab5c877f0` | source `ee2df617-89e6-4593-94fb-dd89e347a1e9` (Primal Male Caveman NPC, 356,096 faces); remesh `cfcddced-ed3d-4d2c-a855-9c5f7f9fdcd4` (5,145 faces); selected native-biped rig `019fe912-89bc-7363-8eb0-67ef625f0f77` | archive, `Character_output.fbx`, `Animation_Walking_withSkin.fbx`, texture PNG |
| `meshy_native_primal_female_001` | `8dcde4448e14eb8ebe31642b75dcfd5ef5af229eefd5ba1abda62fa2cbccfb71` | source `dea7c723-2770-4e90-8b41-cff6499bfeb5` (Primal Female Caveman NPC, 426,473 faces); remesh `c4099988-5a17-4bc4-b777-584fb97bda88` (5,087 faces); selected native-biped rig `019fe918-9955-7605-ad94-477c5084b449`; excluded duplicate `019fe917-5890-7419-9636-70f37e684cae` | archive, `Character_output.fbx`, `Animation_Walking_withSkin.fbx`, texture PNG |

The user observed a 1,249 Meshy balance both before and after the two native
biped rig tasks. It is recorded as observation only; Foundry makes no claim
about provider billing, entitlement, or licensing beyond that statement.

## Independent technical facts

| Candidate | Character / Walking topology | Skin and hierarchy | Walking evidence |
| --- | --- | --- | --- |
| Male | 2,579 vertices; 5,145 polygons in both FBXs | 24 joints, 1 armature, 1 skinned mesh, 0 unweighted vertices; exact canary names and hierarchy | WebP `10d993a83f989cccd128accbc303af119ca9a23f4e6fe318093182764a7a237d`, 254,386 bytes |
| Female | 2,541 vertices; 5,087 polygons in both FBXs | 24 joints, 1 armature, 1 skinned mesh, 0 unweighted vertices; exact canary names and hierarchy | WebP `87bb9f465fc893b6e7d4507f65f6960a59edb60c9b742d5e49d1e780a5178554`, 236,456 bytes |

Both inspection attempt `004` reports are hash-bound, bounded Blender 5.2.0
LTS operations. The male report is
`8591c22fd5594c8621027b22d0b06bf45eacfece535353bb32470ddb9de0aaf5`; the
female report is
`76b017eb13e6e27cd73344a55176e9cf5e00dce8970fa731ef023f8a88f6bc31`.

## Next decision

These candidates are ready for material/visual review of their native walking
motion and for a separate decision on whether any existing canary action may
be adopted through a future, explicitly scoped exact-skeleton corridor. Eating
and butchery semantics remain unresolved; neither is claimed by this package.
