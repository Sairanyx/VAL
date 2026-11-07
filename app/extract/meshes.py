"""Build a colored mesh for each object, by fusing its masked color and depth views.

    python -m app.extract.meshes LIFT_DIR MASKS_DIR OUT_DIR RENDER_DIRS... --ids obj-0001

LIFT_DIR holds assets.json and object_masks.json. Writes OUT_DIR/obj-NNNN.ply and quality.json.
These are for the clean "objects" view. They're approximate shapes, not measured CAD.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def voxel_size_for(extent: float, target_cells: int = 128, floor: float = 0.004) -> float:
    """Return a voxel size that gives an object about `target_cells` across, but not too fine."""
    return max(extent / target_cells, floor)


def keep_largest_parts(
    triangle_clusters: np.ndarray, areas: np.ndarray, share: float
) -> np.ndarray:
    """Return a mask of triangles in clusters with `share` or more of the largest one's area."""
    if not len(triangle_clusters):
        return np.zeros(0, dtype=bool)
    return (areas / max(areas.max(), 1e-12))[triangle_clusters] >= share


def load_cameras(render_dirs: list[Path]) -> dict[str, dict]:
    """Return each view's matrix, intrinsics, image size, and depth path."""
    views = {}
    for render_dir in render_dirs:
        meta = json.loads((render_dir / "cameras.json").read_text())
        for entry in meta["cameras"]:
            views[entry["name"]] = {
                "matrix": np.array(entry["world_to_camera"]),
                "K": np.array(meta["intrinsics"]),
                "width": meta["width"],
                "height": meta["height"],
                "depth": render_dir / "depth" / f"{entry['name']}.npy",
            }
    return views


def build_mesh(asset: dict, masks: list, views: dict, masks_dir: Path, max_views: int = 60):
    """Return an Open3D triangle mesh for one object, and how many views were fused."""
    import open3d as o3d

    low, high = np.array(asset["bbox_min"]), np.array(asset["bbox_max"])
    extent = float((high - low).max())
    voxel = voxel_size_for(extent)
    volume = o3d.pipelines.integration.ScalableTSDFVolume(
        voxel_length=voxel,
        sdf_trunc=voxel * 4,
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
    )
    margin = max(extent * 0.15, 0.05)
    bounds = o3d.geometry.AxisAlignedBoundingBox(low - margin, high + margin)

    step = max(len(masks) // max_views, 1)
    used = 0
    for view_name, mask_id in masks[::step][:max_views]:
        view = views.get(view_name)
        if view is None:
            continue
        ids = np.array(Image.open(masks_dir / "object_mask" / f"{view_name}.png"))
        mask = ids == mask_id
        if not mask.any():
            continue
        depth = np.load(view["depth"])
        depth = np.where(mask, depth, 0).astype(np.float32)
        color = np.array(Image.open(masks_dir / "images" / f"{view_name}.jpg").convert("RGB"))
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(color),
            o3d.geometry.Image(depth),
            depth_scale=1.0,
            depth_trunc=float(np.max(depth)) + 1.0,
            convert_rgb_to_intensity=False,
        )
        camera = view["K"]
        intrinsic = o3d.camera.PinholeCameraIntrinsic(
            view["width"], view["height"], camera[0, 0], camera[1, 1], camera[0, 2], camera[1, 2]
        )
        volume.integrate(rgbd, intrinsic, view["matrix"])
        used += 1

    mesh = volume.extract_triangle_mesh().crop(bounds)
    if len(mesh.triangles):
        clusters, _, areas = mesh.cluster_connected_triangles()
        keep = keep_largest_parts(np.asarray(clusters), np.asarray(areas), share=0.05)
        mesh.remove_triangles_by_mask(~keep)
        mesh.remove_unreferenced_vertices()
    return mesh, used


def main() -> None:
    import open3d as o3d

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lift_dir", type=Path)
    parser.add_argument("masks_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("render_dirs", type=Path, nargs="+")
    parser.add_argument("--ids", nargs="*", help="only these objects")
    parser.add_argument("--max-triangles", type=int, default=60000)
    args = parser.parse_args()

    assets = json.loads((args.lift_dir / "assets.json").read_text())["assets"]
    masks = json.loads((args.lift_dir / "object_masks.json").read_text())
    if args.ids:
        wanted = set(args.ids)
        assets = [asset for asset in assets if asset["object_id"] in wanted]
    views = load_cameras(args.render_dirs)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    quality = {}
    for asset in assets:
        object_id = asset["object_id"]
        mesh, used = build_mesh(asset, masks[object_id], views, args.masks_dir)
        if len(mesh.triangles) > args.max_triangles:
            mesh = mesh.simplify_quadric_decimation(args.max_triangles)
        mesh.compute_vertex_normals()
        o3d.io.write_triangle_mesh(str(args.out_dir / f"{object_id}.ply"), mesh)
        quality[object_id] = {
            "views_fused": used,
            "triangles": len(mesh.triangles),
            "vertices": len(mesh.vertices),
            "watertight": bool(mesh.is_watertight()),
        }
        print(object_id, quality[object_id], flush=True)
    (args.out_dir / "quality.json").write_text(json.dumps(quality, indent=2))


if __name__ == "__main__":
    main()
