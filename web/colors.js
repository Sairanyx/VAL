// One colour per type of equipment, shared by the frames in the scan and by BIM mode.
export const FAULT_COLOR = 0xff2d2d;
export const OTHER_COLOR = 0xc4c9d1;

export const CLASS_COLORS = {
  IfcWall: 0xc7cdd6,
  IfcSlab: 0x6b7280,
  IfcPump: 0xf59e0b,
  IfcTank: 0x22c55e,
  IfcValve: 0xa855f7,
  IfcPipeSegment: 0x3b82f6,
  IfcPipeFitting: 0x93c5fd,
  IfcCableSegment: 0xeab308,
  IfcElectricDistributionBoard: 0x14b8a6,
  IfcLightFixture: 0xfde68a,
  IfcSensor: 0xec4899,
  IfcFlowInstrument: 0xec4899,
  IfcFurniture: 0xfb7185,
  IfcBuildingElementProxy: OTHER_COLOR,
};

// The same groups as app/bim/model.py. Anything else is "Other".
const LABEL_CLASSES = {
  pump: "IfcPump",
  tank: "IfcTank",
  valve: "IfcValve",
  pipe: "IfcPipeSegment",
  hose: "IfcPipeSegment",
  "pipe fitting": "IfcPipeFitting",
  cable: "IfcCableSegment",
  "electrical cabinet": "IfcElectricDistributionBoard",
  "light fixture": "IfcLightFixture",
  sensor: "IfcSensor",
  gauge: "IfcFlowInstrument",
  chair: "IfcFurniture",
  shelf: "IfcFurniture",
};

export function colorForLabel(label) {
  return CLASS_COLORS[LABEL_CLASSES[label]] ?? OTHER_COLOR;
}

export const LEGEND = [
  ["Faulty device", FAULT_COLOR],
  ["Pump", CLASS_COLORS.IfcPump],
  ["Tank", CLASS_COLORS.IfcTank],
  ["Valve", CLASS_COLORS.IfcValve],
  ["Pipe or hose", CLASS_COLORS.IfcPipeSegment],
  ["Pipe fitting", CLASS_COLORS.IfcPipeFitting],
  ["Cable", CLASS_COLORS.IfcCableSegment],
  ["Cabinet", CLASS_COLORS.IfcElectricDistributionBoard],
  ["Light", CLASS_COLORS.IfcLightFixture],
  ["Sensor or gauge", CLASS_COLORS.IfcSensor],
  ["Chair or shelf", CLASS_COLORS.IfcFurniture],
  ["Other", OTHER_COLOR],
];

// Groups for filtering, the same as the frame colours. Plain words, as people say them to Val.
export const TYPE_GROUPS = [
  { key: "pump", text: "Pumps", labels: ["pump"], record: "PUMP", color: CLASS_COLORS.IfcPump },
  { key: "motor", text: "Motors", labels: ["motor"], record: "MOTOR", color: OTHER_COLOR },
  { key: "valve", text: "Valves", labels: ["valve"], record: "VALVE", color: CLASS_COLORS.IfcValve },
  { key: "tank", text: "Tanks", labels: ["tank"], color: CLASS_COLORS.IfcTank },
  {
    key: "pipe",
    text: "Pipes",
    labels: ["pipe", "hose", "pipe fitting"],
    color: CLASS_COLORS.IfcPipeSegment,
  },
  { key: "cable", text: "Cables", labels: ["cable"], color: CLASS_COLORS.IfcCableSegment },
  {
    key: "cabinet",
    text: "Cabinets",
    labels: ["electrical cabinet", "control panel"],
    color: CLASS_COLORS.IfcElectricDistributionBoard,
  },
  {
    key: "light",
    text: "Lights",
    labels: ["light fixture"],
    color: CLASS_COLORS.IfcLightFixture,
  },
  {
    key: "sensor",
    text: "Sensors",
    labels: ["sensor", "gauge"],
    record: "TRANSMITTER|SENSOR",
    color: CLASS_COLORS.IfcSensor,
  },
  {
    key: "furniture",
    text: "Furniture",
    labels: ["chair", "shelf"],
    color: CLASS_COLORS.IfcFurniture,
  },
  {
    key: "portable",
    text: "Carts and tools",
    labels: ["cart", "ladder", "box", "bucket", "barrel", "tool", "bag", "appliance"],
    color: OTHER_COLOR,
  },
  { key: "other", text: "Other", labels: [], color: OTHER_COLOR },
];

export const CONDITION_GROUPS = [
  { key: "attention_required", text: "Attention required", color: 0xef4444 },
  { key: "degraded", text: "Degraded", color: 0xf59e0b },
  { key: "watch", text: "Watch", color: 0xeab308 },
  { key: "healthy", text: "Healthy", color: 0x22c55e },
  { key: "none", text: "No record", color: OTHER_COLOR },
];

export const hex = (color) => `#${color.toString(16).padStart(6, "0")}`;
