"""Data store for Valmet Builder Pack Excel workbook.

Reads asset metadata, current state, telemetry, alarms/events, maintenance history,
and knowledge documents. Works with or without openpyxl by falling back to Python's
built-in zipfile and xml.etree.ElementTree.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EXCEL_EPOCH = dt.datetime(1899, 12, 30)
NS_XML = {
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _excel_date_to_str(val: Any) -> str:
    """Convert an Excel numeric date or timestamp to an ISO string."""
    if val is None:
        return ""
    if isinstance(val, (dt.date, dt.datetime)):
        return val.isoformat()
    try:
        num = float(val)
        date_obj = EXCEL_EPOCH + dt.timedelta(days=num)
        return date_obj.isoformat()
    except (ValueError, TypeError, OverflowError):
        return str(val)


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _safe_str(val: Any) -> str:
    return str(val).strip() if val is not None else ""


@dataclass
class Asset:
    """Plant equipment asset record from Asset_Master."""

    asset_id: str
    tag: str
    asset_class: str
    area_id: str
    area_name: str
    process_context: str
    criticality: str
    installation_date: str
    last_service_date: str
    service_interval_days: int
    connectivity_profile: str = ""
    scene_anchor_id: str = ""
    qr_id: str = ""
    nfc_id: str = ""


@dataclass
class CurrentState:
    """Real-time condition state from Current_State."""

    asset_id: str
    tag: str
    asset_class: str
    area_name: str
    criticality: str
    health_score: float
    condition_state: str
    issue_code: str
    issue_summary: str
    urgency: str
    recommended_next_check: str = ""
    model_confidence: float = 1.0
    last_updated: str = ""
    knowledge_doc_id: str = ""


@dataclass
class TelemetryPoint:
    """Telemetry sample record."""

    timestamp: str
    asset_id: str
    tag: str
    asset_class: str
    area_id: str
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class Event:
    """Historical or active alarm/event from Alarms_Events."""

    event_id: str
    timestamp: str
    asset_id: str
    tag: str
    area_name: str
    event_type: str
    severity: str
    event_code: str
    description: str
    source: str


@dataclass
class WorkOrder:
    """Maintenance history entry from Maintenance_History."""

    work_order_id: str
    asset_id: str
    tag: str
    area_name: str
    opened_at: str
    action: str
    maintenance_type: str
    priority: str
    result: str
    duration_h: float


@dataclass
class ServiceCase:
    """Historical troubleshooting service case."""

    case_id: str
    asset_class: str
    historical_issue_code: str
    historical_interpretation: str
    recommended_next_check: str
    safe_evidence_workflow: str
    severity: str
    knowledge_doc_id: str


@dataclass
class KnowledgeDoc:
    """Guidance document from Knowledge_Docs."""

    doc_id: str
    title: str
    scope: str
    content: str


@dataclass
class DataQualityIssue:
    """Data quality observation from Data_Quality."""

    issue_id: str
    asset_id: str
    tag: str
    issue_type: str
    severity: str
    source_sheet: str
    recommended_handling: str


class DataStore:
    """In-memory searchable store for the Valmet Excel Builder Pack."""

    def __init__(self) -> None:
        self.assets_by_id: dict[str, Asset] = {}
        self.assets_by_tag: dict[str, Asset] = {}
        self.states_by_id: dict[str, CurrentState] = {}
        self.states_by_tag: dict[str, CurrentState] = {}
        self.telemetry_by_id: dict[str, list[TelemetryPoint]] = {}
        self.events_by_id: dict[str, list[Event]] = {}
        self.maintenance_by_id: dict[str, list[WorkOrder]] = {}
        self.service_cases: list[ServiceCase] = []
        self.docs_by_id: dict[str, KnowledgeDoc] = {}
        self.data_quality_by_id: dict[str, list[DataQualityIssue]] = {}
        self.raw_sheets: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def load(cls, workbook_path: Path | str | None = None) -> DataStore:
        """Load and parse the Excel builder pack workbook."""
        path = cls._resolve_path(workbook_path)
        store = cls()
        sheet_rows = _parse_workbook_sheets(path)
        store.raw_sheets = sheet_rows

        # 1. Parse Asset_Master
        for r in sheet_rows.get("Asset_Master", []):
            asset_id = _safe_str(r.get("asset_id"))
            tag = _safe_str(r.get("tag"))
            if not asset_id:
                continue
            asset = Asset(
                asset_id=asset_id,
                tag=tag,
                asset_class=_safe_str(r.get("asset_class")),
                area_id=_safe_str(r.get("area_id")),
                area_name=_safe_str(r.get("area_name")),
                process_context=_safe_str(r.get("process_context")),
                criticality=_safe_str(r.get("criticality")),
                installation_date=_excel_date_to_str(r.get("installation_date")),
                last_service_date=_excel_date_to_str(r.get("last_service_date")),
                service_interval_days=_safe_int(r.get("service_interval_days")),
                connectivity_profile=_safe_str(r.get("connectivity_profile")),
                scene_anchor_id=_safe_str(r.get("scene_anchor_id")),
                qr_id=_safe_str(r.get("qr_id")),
                nfc_id=_safe_str(r.get("nfc_id")),
            )
            store.assets_by_id[asset_id] = asset
            if tag:
                store.assets_by_tag[tag.upper()] = asset

        # 2. Parse Current_State
        for r in sheet_rows.get("Current_State", []):
            asset_id = _safe_str(r.get("asset_id"))
            tag = _safe_str(r.get("tag"))
            if not asset_id:
                continue
            state = CurrentState(
                asset_id=asset_id,
                tag=tag,
                asset_class=_safe_str(r.get("asset_class")),
                area_name=_safe_str(r.get("area_name")),
                criticality=_safe_str(r.get("criticality")),
                health_score=_safe_float(r.get("health_score")),
                condition_state=_safe_str(r.get("condition_state")),
                issue_code=_safe_str(r.get("issue_code")),
                issue_summary=_safe_str(r.get("issue_summary")),
                urgency=_safe_str(r.get("urgency")),
                recommended_next_check=_safe_str(r.get("recommended_next_check")),
                model_confidence=_safe_float(r.get("model_confidence"), 1.0),
                last_updated=_excel_date_to_str(r.get("last_updated")),
                knowledge_doc_id=_safe_str(r.get("knowledge_doc_id")),
            )
            store.states_by_id[asset_id] = state
            if tag:
                store.states_by_tag[tag.upper()] = state

        # 3. Parse Telemetry_Sample_3d
        metric_keys = [
            "process_pressure_bar",
            "process_flow_pct",
            "position_setpoint_pct",
            "position_actual_pct",
            "pneumatic_supply_bar",
            "temperature_c",
            "vibration_rms_mm_s",
            "current_a",
        ]
        for r in sheet_rows.get("Telemetry_Sample_3d", []):
            asset_id = _safe_str(r.get("asset_id"))
            if not asset_id:
                continue
            metrics = {
                k: _safe_float(r[k])
                for k in metric_keys
                if k in r and r[k] is not None and r[k] != ""
            }
            tp = TelemetryPoint(
                timestamp=_excel_date_to_str(r.get("timestamp")),
                asset_id=asset_id,
                tag=_safe_str(r.get("tag")),
                asset_class=_safe_str(r.get("asset_class")),
                area_id=_safe_str(r.get("area_id")),
                metrics=metrics,
            )
            store.telemetry_by_id.setdefault(asset_id, []).append(tp)

        # 4. Parse Alarms_Events
        for r in sheet_rows.get("Alarms_Events", []):
            event_id = _safe_str(r.get("event_id"))
            asset_id = _safe_str(r.get("asset_id"))
            if not event_id or not asset_id:
                continue
            evt = Event(
                event_id=event_id,
                timestamp=_excel_date_to_str(r.get("timestamp")),
                asset_id=asset_id,
                tag=_safe_str(r.get("tag")),
                area_name=_safe_str(r.get("area_name")),
                event_type=_safe_str(r.get("event_type")),
                severity=_safe_str(r.get("severity")),
                event_code=_safe_str(r.get("event_code")),
                description=_safe_str(r.get("description")),
                source=_safe_str(r.get("source")),
            )
            store.events_by_id.setdefault(asset_id, []).append(evt)

        # 5. Parse Maintenance_History
        for r in sheet_rows.get("Maintenance_History", []):
            wo_id = _safe_str(r.get("work_order_id"))
            asset_id = _safe_str(r.get("asset_id"))
            if not wo_id or not asset_id:
                continue
            wo = WorkOrder(
                work_order_id=wo_id,
                asset_id=asset_id,
                tag=_safe_str(r.get("tag")),
                area_name=_safe_str(r.get("area_name")),
                opened_at=_excel_date_to_str(r.get("opened_at")),
                action=_safe_str(r.get("action")),
                maintenance_type=_safe_str(r.get("maintenance_type")),
                priority=_safe_str(r.get("priority")),
                result=_safe_str(r.get("result")),
                duration_h=_safe_float(r.get("duration_h")),
            )
            store.maintenance_by_id.setdefault(asset_id, []).append(wo)

        # 6. Parse Historical_Service_Cases
        for r in sheet_rows.get("Historical_Service_Cases", []):
            case_id = _safe_str(r.get("case_id"))
            if not case_id:
                continue
            sc = ServiceCase(
                case_id=case_id,
                asset_class=_safe_str(r.get("asset_class")),
                historical_issue_code=_safe_str(r.get("historical_issue_code")),
                historical_interpretation=_safe_str(r.get("historical_interpretation")),
                recommended_next_check=_safe_str(r.get("recommended_next_check")),
                safe_evidence_workflow=_safe_str(r.get("safe_evidence_workflow")),
                severity=_safe_str(r.get("severity")),
                knowledge_doc_id=_safe_str(r.get("knowledge_doc_id")),
            )
            store.service_cases.append(sc)

        # 7. Parse Knowledge_Docs
        for r in sheet_rows.get("Knowledge_Docs", []):
            doc_id = _safe_str(r.get("doc_id"))
            if not doc_id:
                continue
            kd = KnowledgeDoc(
                doc_id=doc_id,
                title=_safe_str(r.get("title")),
                scope=_safe_str(r.get("scope")),
                content=_safe_str(r.get("content")),
            )
            store.docs_by_id[doc_id] = kd

        # 8. Parse Data_Quality
        for r in sheet_rows.get("Data_Quality", []):
            issue_id = _safe_str(r.get("issue_id"))
            asset_id = _safe_str(r.get("asset_id"))
            if not issue_id or not asset_id:
                continue
            dq = DataQualityIssue(
                issue_id=issue_id,
                asset_id=asset_id,
                tag=_safe_str(r.get("tag")),
                issue_type=_safe_str(r.get("issue_type")),
                severity=_safe_str(r.get("severity")),
                source_sheet=_safe_str(r.get("source_sheet")),
                recommended_handling=_safe_str(r.get("recommended_handling")),
            )
            store.data_quality_by_id.setdefault(asset_id, []).append(dq)

        return store

    @staticmethod
    def _resolve_path(path: Path | str | None) -> Path:
        if path is not None:
            p = Path(path)
            if p.exists():
                return p
            raise FileNotFoundError(f"Specified workbook not found: {path}")

        matches = sorted(glob.glob("data/*.xlsx"))
        if matches:
            return Path(matches[0])

        parent_matches = sorted(glob.glob("../data/*.xlsx"))
        if parent_matches:
            return Path(parent_matches[0])

        raise FileNotFoundError(
            "No Excel builder pack found in data/*.xlsx. Please deposit the pack file into data/."
        )

    def resolve_asset_id(self, id_or_tag: str) -> str | None:
        """Resolve either an asset_id ('ASSET-017') or tag ('P-005') to asset_id."""
        clean = id_or_tag.strip().upper()
        if clean in self.assets_by_id:
            return clean
        if clean in self.assets_by_tag:
            return self.assets_by_tag[clean].asset_id
        return None

    def get_asset(self, id_or_tag: str) -> Asset | None:
        """Get an asset by ID (e.g. 'ASSET-017') or tag (e.g. 'P-005')."""
        aid = self.resolve_asset_id(id_or_tag)
        return self.assets_by_id.get(aid) if aid else None

    def list_assets(self, asset_class: str | None = None, area: str | None = None) -> list[Asset]:
        """List assets optionally filtered by class or area."""
        results = list(self.assets_by_id.values())
        if asset_class:
            c = asset_class.strip().upper()
            results = [a for a in results if a.asset_class.upper() == c]
        if area:
            a_lower = area.strip().lower()
            results = [
                a for a in results if a_lower in a.area_name.lower() or a_lower in a.area_id.lower()
            ]
        return results

    def get_current_state(self, id_or_tag: str) -> CurrentState | None:
        """Get current condition state for an asset."""
        aid = self.resolve_asset_id(id_or_tag)
        return self.states_by_id.get(aid) if aid else None

    def get_telemetry(self, id_or_tag: str, limit: int = 50) -> list[TelemetryPoint]:
        """Get recent telemetry points for an asset."""
        aid = self.resolve_asset_id(id_or_tag)
        if not aid or aid not in self.telemetry_by_id:
            return []
        points = self.telemetry_by_id[aid]
        return points[-limit:]

    def get_events(
        self, id_or_tag: str, limit: int = 50, severity: str | None = None
    ) -> list[Event]:
        """Get alarms and events for an asset, ordered recent first."""
        aid = self.resolve_asset_id(id_or_tag)
        if not aid or aid not in self.events_by_id:
            return []
        evts = self.events_by_id[aid]
        if severity:
            sev_clean = severity.strip().lower()
            evts = [e for e in evts if e.severity.lower() == sev_clean]
        return list(reversed(evts))[:limit]

    def get_maintenance(self, id_or_tag: str) -> list[WorkOrder]:
        """Get maintenance history work orders for an asset."""
        aid = self.resolve_asset_id(id_or_tag)
        if not aid or aid not in self.maintenance_by_id:
            return []
        return self.maintenance_by_id[aid]

    def get_service_cases(
        self, asset_class: str | None = None, issue_code: str | None = None
    ) -> list[ServiceCase]:
        """Get matching historical service cases."""
        res = self.service_cases
        if asset_class:
            ac = asset_class.strip().upper()
            res = [c for c in res if c.asset_class.upper() == ac]
        if issue_code:
            ic = issue_code.strip().upper()
            res = [c for c in res if c.historical_issue_code.upper() == ic]
        return res

    def get_doc(self, doc_id: str) -> KnowledgeDoc | None:
        """Get a knowledge document by ID."""
        return self.docs_by_id.get(doc_id.strip())

    def list_docs(self, scope: str | None = None) -> list[KnowledgeDoc]:
        """List knowledge docs, optionally matching scope ('PROCESS_PUMP', 'ALL', etc.)."""
        docs = list(self.docs_by_id.values())
        if scope:
            s_up = scope.strip().upper()
            docs = [d for d in docs if d.scope.upper() in (s_up, "ALL")]
        return docs

    def get_data_quality(self, id_or_tag: str) -> list[DataQualityIssue]:
        """Get known data quality issues for an asset."""
        aid = self.resolve_asset_id(id_or_tag)
        return self.data_quality_by_id.get(aid, []) if aid else []

    def get_faulty_target(self) -> tuple[Asset | None, CurrentState | None]:
        """Convenience method returning the target faulty asset ('P-005' / 'ASSET-017')."""
        asset = self.get_asset("P-005")
        state = self.get_current_state("P-005")
        return asset, state


def _parse_workbook_sheets(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse workbook sheets into lists of dicts using zipfile and XML.

    Falls back to openpyxl if already available.
    """
    try:
        import openpyxl  # type: ignore[import-untyped]

        wb = openpyxl.load_workbook(path, data_only=True)
        result: dict[str, list[dict[str, Any]]] = {}
        for sname in wb.sheetnames:
            ws = wb[sname]
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header_row = next(rows_iter)
            except StopIteration:
                continue
            if not header_row or not any(header_row):
                continue
            headers = [
                str(h).strip() if h is not None else f"_col_{i}" for i, h in enumerate(header_row)
            ]
            sheet_data: list[dict[str, Any]] = []
            for r in rows_iter:
                if not any(r):
                    continue
                row_dict = {}
                for i, h in enumerate(headers):
                    val = r[i] if i < len(r) else None
                    row_dict[h] = val
                sheet_data.append(row_dict)
            result[sname] = sheet_data
        return result
    except ImportError:
        pass

    # Pure standard-library fallback (zero dependencies)
    result = {}
    with zipfile.ZipFile(path) as z:
        with z.open("xl/_rels/workbook.xml.rels") as f:
            rels = {
                elem.attrib["Id"]: elem.attrib["Target"]
                for elem in ET.parse(f).findall(
                    "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
                )
            }
        with z.open("xl/workbook.xml") as f:
            sheet_map = {
                elem.attrib["name"]: rels[
                    elem.attrib[
                        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                    ]
                ]
                for elem in ET.parse(f).findall(".//x:sheet", NS_XML)
            }

        for sheet_name, target in sheet_map.items():
            rel_target = target.lstrip("/")
            if not rel_target.startswith("xl/"):
                rel_target = "xl/" + rel_target
            with z.open(rel_target) as sf:
                root = ET.fromstring(sf.read())
                rows_cells: list[dict[str, str]] = []
                for row_elem in root.findall(".//x:row", NS_XML):
                    row_dict: dict[str, str] = {}
                    for c in row_elem.findall("x:c", NS_XML):
                        r_coord = c.attrib.get("r", "")
                        v_elem = c.find("x:v", NS_XML)
                        val = v_elem.text if v_elem is not None else ""
                        match = re.match(r"([A-Z]+)", r_coord)
                        if match:
                            row_dict[match.group(1)] = val or ""
                    if row_dict:
                        rows_cells.append(row_dict)

                if not rows_cells:
                    continue

                # Header is first row
                header_row = rows_cells[0]
                cols = sorted(header_row.keys(), key=lambda c: (len(c), c))
                headers = {col: header_row[col].strip() for col in cols}

                sheet_rows: list[dict[str, Any]] = []
                for r_data in rows_cells[1:]:
                    row_obj: dict[str, Any] = {}
                    for col, hname in headers.items():
                        if not hname:
                            continue
                        row_obj[hname] = r_data.get(col, None)
                    sheet_rows.append(row_obj)
                result[sheet_name] = sheet_rows

    return result


def load_mapping(path: Path | str = "fixtures/mapping.json") -> dict[str, dict[str, Any]]:
    """Load object-to-asset mapping indexed by object_id."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Mapping file not found: {path}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    mappings_list = data.get("mappings", []) if isinstance(data, dict) else data
    return {item["object_id"]: item for item in mappings_list if "object_id" in item}


def load_sample_assets(path: Path | str = "fixtures/copilot_assets.json") -> list[dict[str, Any]]:
    """Load sample 3D asset boxes and centers."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Sample assets file not found: {path}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def join_asset_detail(
    object_id: str,
    sample_assets: list[dict[str, Any]],
    mapping_by_obj: dict[str, dict[str, Any]],
    store: DataStore,
) -> dict[str, Any] | None:
    """Merge 3D geometry, asset metadata, state, alarms, and docs for GET /api/assets/{id}."""
    obj_geom = next((a for a in sample_assets if a.get("object_id") == object_id), None)
    if not obj_geom:
        return None

    map_info = mapping_by_obj.get(object_id)
    result: dict[str, Any] = {
        "object_id": object_id,
        "label": obj_geom.get("label"),
        "confidence_detection": obj_geom.get("confidence", 1.0),
        "center": obj_geom.get("center"),
        "box": obj_geom.get("box"),
        "dimensions": obj_geom.get("dimensions"),
        "mapping": map_info,
    }

    asset_id = map_info.get("asset_id") if map_info else None
    if not asset_id:
        # Detected object with no Excel asset record
        result["asset_record"] = None
        result["current_state"] = None
        result["recent_events"] = []
        result["maintenance_history"] = []
        result["documents"] = []
        return result

    asset = store.get_asset(asset_id)
    state = store.get_current_state(asset_id)
    events = store.get_events(asset_id, limit=10)
    history = store.get_maintenance(asset_id)
    docs = store.list_docs(scope=asset.asset_class if asset else None)

    result["asset_record"] = asdict(asset) if asset else None
    result["current_state"] = asdict(state) if state else None
    result["recent_events"] = [asdict(e) for e in events]
    result["maintenance_history"] = [asdict(h) for h in history]
    result["documents"] = [asdict(d) for d in docs]
    return result
