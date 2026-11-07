"""Turn detected assets, fitted shapes and the estimated room into BIM elements.

Geometry stays in scene coordinates, so the viewer can draw it inside the same root as the scan.
Identity is never upgraded: a mapping made by rule or by eye stays marked unconfirmed.
"""

import uuid

import numpy as np

WALL_THICKNESS = 0.15
SLAB_THICKNESS = 0.1

# Detected label -> (IFC4 entity, predefined type). Unknown labels become generic proxies.
IFC_CLASSES = {
    "pump": ("IfcPump", "NOTDEFINED"),
    "tank": ("IfcTank", "NOTDEFINED"),
    "valve": ("IfcValve", "NOTDEFINED"),
    "pipe": ("IfcPipeSegment", "RIGIDSEGMENT"),
    "hose": ("IfcPipeSegment", "FLEXIBLESEGMENT"),
    "pipe fitting": ("IfcPipeFitting", "NOTDEFINED"),
    "cable": ("IfcCableSegment", "NOTDEFINED"),
    "electrical cabinet": ("IfcElectricDistributionBoard", "NOTDEFINED"),
    "light fixture": ("IfcLightFixture", "NOTDEFINED"),
    "sensor": ("IfcSensor", "NOTDEFINED"),
    "gauge": ("IfcFlowInstrument", "NOTDEFINED"),
    "chair": ("IfcFurniture", "CHAIR"),
    "shelf": ("IfcFurniture", "SHELF"),
}
PROXY = ("IfcBuildingElementProxy", "NOTDEFINED")
NAMESPACE = uuid.UUID("5f0c6b1e-6a43-4a8e-9a55-3c2f1d0e7b11")
_GUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def ifc_guid(*parts: str) -> str:
    """Stable 22-character IFC GlobalId, so re-exports keep the same element IDs."""
    number = uuid.uuid5(NAMESPACE, "/".join(parts)).int
    chars = [_GUID_CHARS[(number >> 126) & 0x3]]
    chars += [_GUID_CHARS[(number >> shift) & 0x3F] for shift in range(120, -1, -6)]
    return "".join(chars)


def identity_confirmed(mapping: dict | None) -> bool:
    if not mapping:
        return False
    method = mapping.get("method", "")
    return not method.startswith("procedural") and "unconfirmed" not in method


def box_from_bounds(lo, hi) -> dict:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return {
        "type": "box",
        "center": ((lo + hi) / 2).round(4).tolist(),
        "axes": np.eye(3).tolist(),
        "size": np.maximum(hi - lo, 0.01).round(4).tolist(),
    }


def asset_geometry(asset: dict, shape: dict | None) -> tuple[dict, str]:
    if shape and shape.get("use_shape"):
        if shape["type"] == "cylinder":
            keys = ("center", "axis", "radius", "height")
            return {"type": "cylinder", **{k: shape[k] for k in keys}}, "fitted cylinder"
        keys = ("center", "axes", "size")
        return {"type": "box", **{k: shape[k] for k in keys}}, "fitted box"
    return box_from_bounds(asset["bbox_min"], asset["bbox_max"]), "axis-aligned bounding box"


def asset_element(scene_id: str, asset: dict, shape: dict | None, mesh: dict | None = None) -> dict:
    label = asset.get("label", "object")
    ifc_class, predefined = IFC_CLASSES.get(label, PROXY)
    mapping = asset.get("mapping")
    geometry, source = asset_geometry(asset, shape)
    psets = {
        "Valmet_Identification": {
            "ObjectId": asset["object_id"],
            "DetectedLabel": label,
            "LabelGrade": asset.get("label_grade"),
            "LabelConfidence": asset.get("label_confidence"),
            "Description": asset.get("description") or None,
            "Mobility": asset.get("mobility"),
            "MobilityReason": asset.get("mobility_reason"),
            "IdentityConfirmed": identity_confirmed(mapping),
            "Status": asset.get("status"),
            "OperatorName": asset.get("name"),
            "CopiedFrom": asset.get("duplicated_from"),
        },
        "Valmet_Geometry": {
            "Source": f"scan surface mesh, {mesh['voxel'] * 100:.1f} cm voxels" if mesh else source,
            "Simplified": source,
            "FitScore": shape.get("score") if shape and shape.get("use_shape") else None,
            "SplatCount": asset.get("splats"),
            "ViewCount": asset.get("views"),
        },
    }
    if mapping:
        psets["Valmet_Mapping"] = {
            "Tag": mapping.get("tag"),
            "AssetId": mapping.get("asset_id"),
            "Method": mapping.get("method"),
            "Confidence": mapping.get("confidence"),
            "Note": mapping.get("note"),
        }
    tag = mapping.get("tag") if mapping else None
    unsure = tag and not identity_confirmed(mapping)
    title = f"{tag}?" if unsure else tag or asset.get("name") or label
    return {
        "guid": ifc_guid(scene_id, asset["object_id"]),
        "object_id": asset["object_id"],
        "ifc_class": ifc_class,
        "predefined_type": predefined,
        "name": f"{title} ({asset['object_id']})",
        "geometry": geometry,
        "psets": psets,
    }


def room_elements(scene_id: str, room: dict) -> list[dict]:
    up = np.asarray(room["up"])
    up_axis = int(np.argmax(np.abs(up)))
    first, second = room["axes"]
    faces = room["faces"]
    lo = np.array([faces["first_min"], faces["second_min"]]) - WALL_THICKNESS
    hi = np.array([faces["first_max"], faces["second_max"]]) + WALL_THICKNESS
    floor = room["floor_along_up"]
    height = room["ceiling_height"]

    def bounds(horizontal_lo, horizontal_hi, bottom, top):
        a, b = np.zeros(3), np.zeros(3)
        a[[first, second]], b[[first, second]] = horizontal_lo, horizontal_hi
        # Positions along the up axis: up[up_axis] * (floor + height above floor).
        ends = sorted(up[up_axis] * (floor + h) for h in (bottom, top))
        a[up_axis], b[up_axis] = ends
        return box_from_bounds(a, b)

    t = WALL_THICKNESS
    walls = {
        "first_min": ([lo[0], lo[1]], [lo[0] + t, hi[1]]),
        "first_max": ([hi[0] - t, lo[1]], [hi[0], hi[1]]),
        "second_min": ([lo[0], lo[1]], [hi[0], lo[1] + t]),
        "second_max": ([lo[0], hi[1] - t], [hi[0], hi[1]]),
    }
    note = "Estimated from scan density, not surveyed. Doors and openings are not modelled."
    elements = []
    for key, (a, b) in walls.items():
        elements.append(
            {
                "guid": ifc_guid(scene_id, "wall", key),
                "object_id": None,
                "ifc_class": "IfcWall",
                "predefined_type": "NOTDEFINED",
                "name": f"Wall {key.replace('_', ' ')} (estimated)",
                "geometry": bounds(a, b, 0.0, height),
                "psets": {
                    "Valmet_Geometry": {
                        "Source": "estimated room boundary",
                        "Method": room["method"],
                        "Support": room["wall_support"][key],
                        "Note": note,
                    }
                },
            }
        )
    elements.append(
        {
            "guid": ifc_guid(scene_id, "floor"),
            "object_id": None,
            "ifc_class": "IfcSlab",
            "predefined_type": "FLOOR",
            "name": "Floor slab (estimated)",
            "geometry": bounds(lo, hi, -SLAB_THICKNESS, 0.0),
            "psets": {"Valmet_Geometry": {"Source": "scan floor height", "Note": note}},
        }
    )
    return elements


def build_model(
    assets_file: dict, shapes: dict, room: dict, meshes: dict[str, dict] | None = None
) -> dict:
    """Meshes, keyed by object ID, replace an element's simplified shape where they exist."""
    scene_id = assets_file.get("scene_id", "scene")
    meshes = meshes or {}
    elements = room_elements(scene_id, room)
    for asset in assets_file["assets"]:
        object_id = asset["object_id"]
        mesh = meshes.get(object_id)
        elements.append(asset_element(scene_id, asset, shapes.get(object_id), mesh))
    return {
        "scene_id": scene_id,
        "units": assets_file.get("units", "metres"),
        "room": room,
        "fault_tag": assets_file.get("fault_tag", "P-005"),
        "elements": elements,
    }
