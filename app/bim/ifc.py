"""Write a BIM model as an IFC4 STEP file, without extra dependencies.

The IFC file is Z-up in metres with the floor at Z = 0. Boxes and cylinders become extruded
solids; properties go into Valmet_* property sets. Open it in any IFC viewer, such as Bonsai.
"""

import datetime as dt
from pathlib import Path

import numpy as np

from app.bim.model import ifc_guid


def ifc_frame(room: dict) -> tuple[np.ndarray, float]:
    """Rotation from scene to IFC axes (X, Y horizontal, Z up), and the floor along up."""
    up = np.asarray(room["up"], float)
    ex = np.zeros(3)
    ex[room["axes"][0]] = 1.0
    ey = np.cross(up, ex)
    return np.stack([ex, ey, up]), room["floor_along_up"]


def string(text: str) -> str:
    out = []
    for char in text.replace("\\", "\\\\").replace("'", "''"):
        out.append(char if 32 <= ord(char) < 127 else f"\\X2\\{ord(char):04X}\\X0\\")
    return "'" + "".join(out) + "'"


def real(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def value(item) -> str:
    if isinstance(item, bool):
        return f"IFCBOOLEAN(.{'T' if item else 'F'}.)"
    if isinstance(item, int):
        return f"IFCINTEGER({item})"
    if isinstance(item, float):
        return f"IFCREAL({real(item)})"
    text = str(item)
    return f"IFCTEXT({string(text)})" if len(text) > 255 else f"IFCLABEL({string(text)})"


class Writer:
    def __init__(self):
        self.lines: list[str] = []

    def add(self, entity: str) -> str:
        self.lines.append(entity)
        return f"#{len(self.lines)}"

    def point(self, xyz) -> str:
        return self.add(f"IFCCARTESIANPOINT(({','.join(real(v) for v in xyz)}))")

    def direction(self, xyz) -> str:
        return self.add(f"IFCDIRECTION(({','.join(real(v) for v in xyz)}))")

    def placement(self, origin, axis=None, ref=None) -> str:
        args = [self.point(origin)]
        args += [self.direction(axis) if axis is not None else "$"]
        args += [self.direction(ref) if ref is not None else "$"]
        return self.add(f"IFCAXIS2PLACEMENT3D({','.join(args)})")


def orthonormal(axis, ref) -> tuple[np.ndarray, np.ndarray]:
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    ref = np.asarray(ref, float) - np.dot(ref, axis) * axis
    if np.linalg.norm(ref) < 1e-6:
        ref = np.cross(axis, [1.0, 0, 0] if abs(axis[0]) < 0.9 else [0, 1.0, 0])
    return axis, ref / np.linalg.norm(ref)


def solid(w: Writer, geometry: dict, rotation: np.ndarray, floor: float) -> tuple[str, str]:
    """Local placement position and swept solid for one element, in IFC coordinates."""
    center = rotation @ np.asarray(geometry["center"], float) - [0, 0, floor]
    origin2d = w.add(f"IFCAXIS2PLACEMENT2D({w.point((0.0, 0.0))},$)")
    if geometry["type"] == "cylinder":
        axis, ref = orthonormal(rotation @ np.asarray(geometry["axis"], float), [1.0, 0, 0])
        profile = w.add(f"IFCCIRCLEPROFILEDEF(.AREA.,$,{origin2d},{real(geometry['radius'])})")
        depth = geometry["height"]
    else:
        axes = [rotation @ np.asarray(a, float) for a in geometry["axes"]]
        if np.dot(np.cross(axes[0], axes[1]), axes[2]) < 0:
            axes[2] = -axes[2]
        axis, ref = orthonormal(axes[2], axes[0])
        sx, sy, depth = geometry["size"]
        profile = w.add(f"IFCRECTANGLEPROFILEDEF(.AREA.,$,{origin2d},{real(sx)},{real(sy)})")
    place = w.placement(center, axis, ref)
    start = w.placement((0.0, 0.0, -depth / 2))
    up = w.direction((0.0, 0.0, 1.0))
    body = w.add(f"IFCEXTRUDEDAREASOLID({profile},{start},{up},{real(depth)})")
    return place, body


def write_ifc(model: dict, path: Path, timestamp: str | None = None) -> None:
    rotation, floor = ifc_frame(model["room"])
    scene_id = model["scene_id"]
    w = Writer()
    world = w.placement((0.0, 0.0, 0.0))
    context = w.add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,{world},$)")
    body_ctx = w.add(
        f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,{context},$,.MODEL_VIEW.,$)"
    )
    units = [
        w.add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)"),
        w.add("IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)"),
        w.add("IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)"),
        w.add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)"),
    ]
    unit_set = w.add(f"IFCUNITASSIGNMENT(({','.join(units)}))")
    name = string(scene_id)
    project = w.add(
        f"IFCPROJECT('{ifc_guid(scene_id, 'project')}',$,{name},"
        f"'Simulated BIM from a 3D scan',$,$,$,({context}),{unit_set})"
    )
    root_place = w.add(f"IFCLOCALPLACEMENT($,{w.placement((0.0, 0.0, 0.0))})")
    site = w.add(
        f"IFCSITE('{ifc_guid(scene_id, 'site')}',$,'Site',$,$,{root_place},$,$,.ELEMENT.,$,$,$,$,$)"
    )
    building = w.add(
        f"IFCBUILDING('{ifc_guid(scene_id, 'building')}',$,'Building',$,$,{root_place},"
        "$,$,.ELEMENT.,$,$,$)"
    )
    storey = w.add(
        f"IFCBUILDINGSTOREY('{ifc_guid(scene_id, 'storey')}',$,'Equipment level',$,$,"
        f"{root_place},$,$,.ELEMENT.,0.)"
    )
    space = w.add(
        f"IFCSPACE('{ifc_guid(scene_id, 'space')}',$,{name},'Scanned room',$,{root_place},"
        "$,$,.ELEMENT.,.INTERNAL.,$)"
    )
    for parent, child in ((project, site), (site, building), (building, storey), (storey, space)):
        w.add(f"IFCRELAGGREGATES('{ifc_guid(scene_id, 'agg', parent)}',$,$,$,{parent},({child}))")

    products = []
    for element in model["elements"]:
        place, body = solid(w, element["geometry"], rotation, floor)
        local = w.add(f"IFCLOCALPLACEMENT({root_place},{place})")
        shape = w.add(f"IFCSHAPEREPRESENTATION({body_ctx},'Body','SweptSolid',({body}))")
        definition = w.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({shape}))")
        product = w.add(
            f"{element['ifc_class'].upper()}('{element['guid']}',$,{string(element['name'])},"
            f"$,$,{local},{definition},$,.{element['predefined_type']}.)"
        )
        products.append(product)
        for pset_name, props in element["psets"].items():
            props = [
                w.add(f"IFCPROPERTYSINGLEVALUE({string(key)},$,{value(item)},$)")
                for key, item in props.items()
                if item is not None
            ]
            if not props:
                continue
            pset = w.add(
                f"IFCPROPERTYSET('{ifc_guid(element['guid'], pset_name)}',$,"
                f"{string(pset_name)},$,({','.join(props)}))"
            )
            w.add(
                f"IFCRELDEFINESBYPROPERTIES('{ifc_guid(element['guid'], pset_name, 'rel')}',"
                f"$,$,$,({product}),{pset})"
            )
    w.add(
        f"IFCRELCONTAINEDINSPATIALSTRUCTURE('{ifc_guid(scene_id, 'contained')}',$,$,$,"
        f"({','.join(products)}),{storey})"
    )

    stamp = timestamp or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S")
    header = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');",
        f"FILE_NAME({string(path.name)},'{stamp}',(''),(''),'','app.bim','');",
        "FILE_SCHEMA(('IFC4'));",
        "ENDSEC;",
        "DATA;",
    ]
    body = [f"#{index}={line};" for index, line in enumerate(w.lines, start=1)]
    path.write_text("\n".join(header + body + ["ENDSEC;", "END-ISO-10303-21;", ""]))
