// Which object is under the pointer. The nearest object wins, so nothing behind it can be picked.
// Two exceptions keep that usable:
// - Boxes the camera is inside are ignored, unless nothing else is under the pointer.
// - Long, thin things (pipes, hoses, cables) have mostly empty boxes that can span the room, so they
//   only count where their actual surface is under the pointer.
// Shapes need two-sided materials, so a ray inside a shape still hits its far side.
//
// Each candidate: { mesh, volume, thin, surface }. `surface(raycaster)` gives the distance to the
// object's real surface along the ray, or null where there is none; thin objects without it are
// only picked when nothing else is under the pointer.

export const THIN_LABELS = new Set(["pipe", "pipe fitting", "hose", "cable"]);

// `keep` drops hits, such as those above a section cut.
export function pickFront(raycaster, candidates, keep = () => true) {
  const byMesh = new Map(candidates.map((c) => [c.mesh, c]));
  const spans = new Map();
  for (const hit of raycaster.intersectObjects([...byMesh.keys()], false).filter(keep)) {
    const candidate = byMesh.get(hit.object);
    const span = spans.get(candidate);
    if (span) span.hits += 1;
    else spans.set(candidate, { candidate, entry: hit.distance, hits: 1 });
  }
  const all = [...spans.values()];
  // One hit on a closed shape means the ray starts inside it.
  const outside = all.filter((s) => s.hits > 1);
  const solid = outside.filter((s) => !s.candidate.thin).sort((a, b) => a.entry - b.entry);
  const front = solid[0];
  let thin = null;
  let thinAt = front ? front.entry : Infinity;
  for (const span of outside.filter((s) => s.candidate.thin)) {
    const at = span.candidate.surface?.(raycaster);
    if (at !== null && at !== undefined && at < thinAt) {
      thin = span;
      thinAt = at;
    }
  }
  if (thin) return thin.candidate;
  if (front) return front.candidate;
  // Only thin things without a known surface, or boxes around the camera, are left.
  if (outside.length) return outside.sort((a, b) => a.entry - b.entry)[0].candidate;
  return all.length ? all.reduce((a, b) => (b.candidate.volume < a.candidate.volume ? b : a)).candidate : null;
}
