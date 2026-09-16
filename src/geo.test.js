import { readFileSync } from "fs";
import { findDistrict, parseAddress } from "./geo.js";

const fc = JSON.parse(readFileSync(new URL("../public/data/districts.geojson", import.meta.url), "utf8"));
const DISTRICTS = fc.features
  .map((f) => ({ ...f.properties, geometry: f.geometry }))
  .sort((a, b) => a.id - b.id);

const cases = [
  ["Aviator Pool", -104.89483, 39.75642, 2],
  ["Founders Green / 29th & Roslyn", -104.90053, 39.7577, 2],
  ["Puddle Jumper Pool", -104.88568, 39.75162, 4],
  ["Westerly Creek interior", -104.88, 39.757, 3],
  ["Eastbridge interior", -104.873, 39.757, 5],
  ["CP West interior", -104.895, 39.763, 6],
  ["RTD station area", -104.8918, 39.7699, 7],
  ["Willow Park west", -104.896, 39.7945, 9],
  ["F-15 Pool", -104.86692, 39.7568, 5],
  ["Aurora 26th Ave (80010 edge)", -104.85596, 39.75469, 5],
  ["Jet Stream Pool", -104.88166, 39.7666, 6],
  ["The Cube", -104.89087, 39.78577, 8],
  ["Conservatory Green Plaza", -104.89224, 39.78702, 8],
  ["Maverick Pool", -104.88598, 39.78912, 8],
  ["Beeler Park Plaza", -104.876, 39.8004, 11],
  ["Splash Landing", -104.8688, 39.8052, 11],
  ["Fred Thomas Park (outside)", -104.9015, 39.7528, null],
  ["80012 south Aurora (outside)", -104.84, 39.7, null],
];

let failed = 0;
for (const [label, lng, lat, expected] of cases) {
  const hit = findDistrict(lng, lat, DISTRICTS);
  const got = hit ? hit.id : null;
  const ok = got === expected;
  if (!ok) {
    failed += 1;
    console.error(`FAIL ${label}: expected ${expected}, got ${got}`);
  } else {
    console.log(`ok   ${label} → ${got ?? "outside"}`);
  }
}

const parseCases = [
  ["5000 N Beeler St", { number: "5000", street: "Beeler", dir: "N" }],
  ["9345 E 56th Ave, Denver CO 80238", { number: "9345", street: "56th", dir: "E" }],
  ["11001 E 51 Ave", { number: "11001", street: "51st", dir: "E" }],
  ["4939 N Central Park Blvd", { number: "4939", street: "Central Park", dir: "N" }],
  ["4893 N Xenia St Unit 101", { number: "4893", street: "Xenia", unit: "101" }],
  ["8054 E 28th Ave", { number: "8054", street: "28th", dir: "E" }],
];

for (const [input, expect] of parseCases) {
  const got = parseAddress(input);
  const bits = Object.entries(expect).filter(([k, v]) => String(got[k] || "") !== String(v));
  if (bits.length) {
    failed += 1;
    console.error(`FAIL parse ${input}: ${JSON.stringify(got)}`);
  } else {
    console.log(`ok   parse ${input} → ${got.number} ${got.dir || ""} ${got.street}`.replace(/ +/g, " "));
  }
}

if (failed) {
  console.error(`\n${failed} failed`);
  process.exit(1);
}
console.log("\nall geo tests passed");
