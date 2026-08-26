const fs = require("fs");
const path = require("path");

const source = fs.readFileSync(
    path.join(__dirname, "..", "alkalmazas", "statikus", "alkalmazas.js"),
    "utf8",
);
const helperStart = source.indexOf("const matrixMonthNames");
const helperEnd = source.indexOf("function renderContractMatrixModern");

if (helperStart < 0 || helperEnd < 0) {
    throw new Error("A havi matrix segedfuggvenyei nem talalhatok.");
}

eval(`${source.slice(helperStart, helperEnd)}
const groups = buildMatrixMonthGroups(
    [
        { stage_date: "2023-01-10", code: "M_1" },
        { stage_date: "2023-03-05", code: "M_2" },
        { stage_date: "2023-03-20", code: "M_3" },
    ],
    "2023-01-01",
);
if (groups.length !== 3) throw new Error("A folyamatos honaplista hossza hibas.");
if (groups[1].key !== "2023-02" || groups[1].columns.length !== 0) {
    throw new Error("Az ures februar nem jelent meg a honaplistaban.");
}
if (groups[2].columns.length !== 2) {
    throw new Error("Az azonos havi merfoldkovek csoportositasa hibas.");
}
`);

console.log("Havi matrix idovonal: OK");
