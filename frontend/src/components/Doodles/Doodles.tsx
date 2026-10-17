import { VOLCANO_FILL, VOLCANO_POINTS } from "./volcanoPoints";
import "./Doodles.css";

export function Doodles() {
  return (
    <>
      <div className="pink-tab" aria-hidden="true" />
      <RnaSeqDoodle />
      <HeatmapDoodle />
      <VolcanoDoodle />
      <PathwayDoodle />
    </>
  );
}

function RnaSeqDoodle() {
  return (
    <svg className="doodle doodle--rna" viewBox="0 0 260 215" aria-hidden="true">
      <text x="18" y="31" style={{ fontSize: 24, fontWeight: 500, letterSpacing: ".2px" }} transform="rotate(-3 18 31)">
        RNA-seq
      </text>
      <path d="M19 39q59 -1 111 0" className="pink" />
      <path className="ink" d="M13 134 H227 M127 141 V168 m-5 -7 5 7 5-7" />
      <path
        className="ink"
        d="M34 122h20 M42 108h19 M70 99h27 M67 82h20 M79 67h30 M111 111h20 M129 93h18 M138 116h21 M158 104h19 M178 94h18 M198 103h17"
        style={{ stroke: "#a9bed9", strokeWidth: 3.2, opacity: 0.9 }}
      />
      <path className="pink" d="M84 119h16 M97 94h17 M178 101h13" />
      <text x="193" y="68" style={{ fontSize: 15 }} transform="rotate(-8 193 68)">
        reads
      </text>
      <path className="ink" d="M192 75l-21 20 3-7m-3 7 8-1" />
      <text x="106" y="195" style={{ fontSize: 17 }} transform="rotate(2 106 195)">
        counts
      </text>
    </svg>
  );
}

// 0 = neutral, 1 = pale blue, 2 = blue, 3 = pink (same grid as the reference).
const HEAT_FILLS = ["#f6f5ef", "#d2dced", "#bfd5ed", "#f7dbdf"];
const HEAT_GRID = [
  [1, 0, 1, 2, 0, 0],
  [0, 0, 2, 1, 0, 3],
  [1, 3, 0, 2, 3, 0],
  [0, 1, 2, 0, 0, 3],
  [0, 0, 0, 1, 1, 0],
];

function HeatmapDoodle() {
  return (
    <svg className="doodle doodle--heat" viewBox="0 0 252 183" aria-hidden="true">
      <g>
        {HEAT_GRID.flatMap((row, r) =>
          row.map((v, c) => (
            <rect
              key={`${r}-${c}`}
              x={73 + c * 22}
              y={29 + r * 23}
              width="21"
              height="22"
              fill={HEAT_FILLS[v]}
              fillOpacity=".74"
              stroke="#8999ae"
              strokeWidth=".7"
            />
          )),
        )}
      </g>
      <g style={{ fontStyle: "normal" }}>
        <text x="8" y="47">Gene1</text>
        <text x="8" y="70">Gene2</text>
        <text x="8" y="93">Gene3</text>
        <text x="8" y="116">Gene4</text>
        <text x="15" y="137">···</text>
        <text x="76" y="163">S1</text>
        <text x="120" y="163">S2</text>
        <text x="163" y="163">S3</text>
        <text x="204" y="163">S4</text>
      </g>
    </svg>
  );
}

function VolcanoDoodle() {
  return (
    <svg className="doodle doodle--volcano" viewBox="0 0 265 218" aria-hidden="true">
      <g className="ink">
        <path d="M42 13V180H253 M42 180l-5-9m5 9 6-9 M253 180l-8-6m8 6-8 6" />
        <path d="M42 163H253" strokeDasharray="4 6" opacity=".68" />
        <path d="M108 30V180 M170 30V180" strokeDasharray="5 6" opacity=".65" />
      </g>
      <g>
        {VOLCANO_POINTS.map(([cx, cy, r, group, opacity], i) => (
          <circle key={i} cx={cx} cy={cy} r={r} fill={VOLCANO_FILL[group]} opacity={opacity} />
        ))}
      </g>
      <text x="6" y="103" transform="rotate(-90 6 103)" style={{ fontSize: 17 }}>
        −log₁₀(P)
      </text>
      <text x="108" y="207" style={{ fontSize: 17 }}>
        log₂ FC
      </text>
    </svg>
  );
}

function PathwayDoodle() {
  return (
    <svg className="doodle doodle--pathway" viewBox="0 0 236 154" aria-hidden="true">
      <g className="ink">
        <circle cx="27" cy="60" r="12" />
        <circle cx="95" cy="17" r="12" />
        <circle cx="68" cy="120" r="12" />
        <path d="M38 50L83 24 M34 70l27 38 M67 31l14-7m-4 2 4-2-1 5 M46 93l14 14m-4-4 4 4-1-6" />
      </g>
      <text x="115" y="83" style={{ fontSize: 18, fontStyle: "normal" }}>
        Pathway
      </text>
      <text x="114" y="108" style={{ fontSize: 18, fontStyle: "normal" }}>
        enrichment
      </text>
      <path className="pink" d="M111 115 Q165 110 218 112" />
    </svg>
  );
}
