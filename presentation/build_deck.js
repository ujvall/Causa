// Generates presentation/CAUSA_Final_Presentation.pptx (native, editable shapes, text, table and chart).
//
//   node presentation/build_deck.js
//
// Requires: node 18+, `pptxgenjs`. Screenshots in presentation/assets/ are produced by capture_studio.py.
// Optional: set PPTX_APPLY_THEME to the path of a script exporting applyTheme(deckPath, THEME) to write
// the theme colours into the deck (see README.md). The deck renders correctly without it.

const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const HERE = __dirname;
const ASSETS = path.join(HERE, "assets");
const OUT = path.join(HERE, "CAUSA_Final_Presentation.pptx");

// ---------- palette and type ----------
// Canvas (light) and chrome
const PAPER = "09090A", INK = "ECECEE", GREY = "7C7C84", CARD = "121214", CARDLINE = "2B2B31", ACC = "22D3EE";
// Dark figure panels (graphs, code, consoles, screenshots keep the original graph/code colours)
const PANEL = "121214", SURF2 = "1C1C21", LINE = "2B2B31";
const TXT = "ECECEE", MUTED = "8E8E96";
const CYAN = "22D3EE", BLUE = "60A5FA", VIOLET = "A78BFA", TEAL = "2DD4BF", ORANGE = "FB923C", GREEN = "86EFAC", RED = "F87171";
const BG = PANEL;
const SANS = "Inter", SERIF = "Inter", MONO = "Consolas";
// the same hues, darkened for use on the light canvas
const CV = { [CYAN]: ACC, [ORANGE]: ACC, [TEAL]: "2B6B57", [GREEN]: "2B6B57", [BLUE]: "2F5D8A", [VIOLET]: "3B3A7A", [RED]: "A32020", [TXT]: INK, [MUTED]: GREY, [LINE]: CARDLINE, [BG]: INK };
const cv = (c) => (c && CV[c] ? CV[c] : c);

const THEME = {
  name: "CAUSA Matte",
  headFontFace: SERIF,
  bodyFontFace: SANS,
  colors: {
    dk1: INK, lt1: PAPER, dk2: PANEL, lt2: CARD,
    accent1: ACC, accent2: VIOLET, accent3: GREEN, accent4: BLUE, accent5: GREY, accent6: CARDLINE,
    hlink: ACC, folHlink: VIOLET,
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 in
pres.theme = { headFontFace: SERIF, bodyFontFace: SANS };
pres.title = "CAUSA - A Compiler for Explainable and Counterfactual Programming";
pres.subject = "Compiler Design project - final review";
pres.author = "";

pres.defineSlideMaster({ title: "CAUSA_TITLE", background: { color: PAPER }, objects: [] });
pres.defineSlideMaster({
  title: "CAUSA_CONTENT",
  background: { color: PAPER },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.13, h: 0.75, fontFace: SANS, fontSize: 28, bold: true, color: INK, align: "left", valign: "top", margin: 0, charSpacing: -0.5 }, text: "" } },
  ],
  slideNumber: { x: 12.13, y: 7.05, w: 0.6, h: 0.3, fontFace: SANS, fontSize: 10, color: GREY, align: "right" },
});

// ---------- helpers ----------
let n = 0;
const oid = (s) => `${s}-${++n}`;
let DARKS = []; // dark panels on the current slide: text and cards placed over them use light-on-dark styling
const inDark = (cx, cy) => DARKS.some((r) => cx >= r.x && cx <= r.x + r.w && cy >= r.y && cy <= r.y + r.h);

function panel(slide, x, y, w, h, o = {}) {
  DARKS.push({ x, y, w, h });
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: PANEL }, line: o.line || { color: PANEL, width: 1 }, objectName: oid("panel") });
}
function T(slide, text, x, y, w, h, o = {}) {
  const dark = true;
  const opts = Object.assign({ x, y, w, h, fontFace: SANS, fontSize: 16, margin: 0, valign: "top", isTextBox: true, objectName: oid("text") }, o);
  const fix = (c) => (dark ? c : cv(c));
  opts.color = o.color ? fix(o.color) : dark ? TXT : INK;
  if (Array.isArray(text)) text = text.map((r) => (r.options && r.options.color ? Object.assign({}, r, { options: Object.assign({}, r.options, { color: fix(r.options.color) }) }) : r));
  slide.addText(text, opts);
}
function card(slide, x, y, w, h, o = {}) {
  const dark = inDark(x + w / 2, y + h / 2);
  let line, fill;
  fill = dark ? SURF2 : CARD; line = o.line || { color: LINE, width: 1 };
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line, objectName: oid("card") });
}
function chip(slide, text, x, y, w, h, color, o = {}) {
  const dark = true;
  const c = dark ? color : cv(color);
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: h / 2, fill: { color: dark ? PANEL : CARD }, line: { color: c, width: 1 }, objectName: oid("chip") });
  T(slide, text, x, y, w, h, Object.assign({ fontSize: 12, color, align: "center", valign: "middle", bold: true }, o));
}
function arrow(slide, x1, y1, x2, y2, color = MUTED, width = 1.5, head = true) {
  const dark = true;
  const c = dark ? color : (color === MUTED || color === "5B6B7B" ? GREY : cv(color));
  slide.addShape(pres.ShapeType.line, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
    flipH: x2 < x1, flipV: y2 < y1,
    line: Object.assign({ color: c, width }, head ? { endArrowType: "triangle" } : {}),
    objectName: oid("arrow"),
  });
}
function node(slide, x, y, w, h, label, color, sub, fill = SURF2, size = 15) {
  slide.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.06, fill: { color: fill }, line: { color, width: 1.5 }, objectName: oid("node") });
  if (sub) {
    T(slide, label, x, y + 0.05, w, h * 0.55, { fontFace: MONO, fontSize: size, color: TXT, align: "center", valign: "middle", bold: true });
    T(slide, sub, x, y + h * 0.55, w, h * 0.4, { fontSize: 11, color: MUTED, align: "center", valign: "top" });
  } else {
    T(slide, label, x, y, w, h, { fontFace: MONO, fontSize: size, color: TXT, align: "center", valign: "middle", bold: true });
  }
}

// CAUSA syntax highlighting -> pptxgenjs text runs (colours unchanged; always used on dark panels)
const KEYWORDS = new Set(["input", "let", "show", "explain", "whatif", "impact", "assert"]);
function highlight(src, size = 15) {
  const runs = [];
  const lines = src.split("\n");
  lines.forEach((line, li) => {
    const re = /(#.*$)|(\b[A-Za-z_][A-Za-z0-9_]*\b)|(\d+(?:\.\d+)?)|([=*+\-/<>]+)|(\s+|.)/g;
    let m;
    const start = runs.length;
    while ((m = re.exec(line)) !== null) {
      const base = { fontFace: MONO, fontSize: size };
      if (m[1]) runs.push({ text: m[1], options: Object.assign({ color: "6B7A89", italic: true }, base) });
      else if (m[2]) {
        const kw = KEYWORDS.has(m[2]) || m[2] === "true" || m[2] === "false";
        runs.push({ text: m[2], options: Object.assign({ color: kw ? VIOLET : TXT, bold: kw }, base) });
      } else if (m[3]) runs.push({ text: m[3], options: Object.assign({ color: ORANGE }, base) });
      else if (m[4]) runs.push({ text: m[4], options: Object.assign({ color: CYAN }, base) });
      else runs.push({ text: m[5], options: Object.assign({ color: TXT }, base) });
    }
    if (runs.length === start) runs.push({ text: " ", options: { color: TXT, fontFace: MONO, fontSize: size } });
    if (li < lines.length - 1) runs[runs.length - 1].options.breakLine = true;
  });
  return runs;
}
function consoleRuns(lines, size = 13) {
  return lines.map((l, i) => {
    const [text, color] = Array.isArray(l) ? l : [l, TXT];
    return { text: text === "" ? " " : text, options: { fontFace: MONO, fontSize: size, color, breakLine: i < lines.length - 1 } };
  });
}
function codeCard(slide, x, y, w, h, label, runs) {
  panel(slide, x, y, w, h);
  if (label) T(slide, label, x + 0.25, y + 0.15, w - 0.5, 0.3, { fontSize: 11, color: MUTED, bold: true, charSpacing: 1 });
  T(slide, runs, x + 0.25, y + (label ? 0.5 : 0.25), w - 0.5, h - (label ? 0.65 : 0.4), { valign: "top", paraSpaceAfter: 2 });
}
function title(slide, text) { slide.addText(text, { placeholder: "title" }); }
function contentSlide(section, text, notes) {
  DARKS = [];
  const s = pres.addSlide({ masterName: "CAUSA_CONTENT", sectionTitle: section });
  title(s, text);
  T(s, "CAUSA   " + section, 0.6, 7.05, 6, 0.3, { fontSize: 10, color: GREY });
  s.addNotes(notes);
  return s;
}

// =====================================================================
// 1. Title
// =====================================================================
pres.addSection({ title: "Opening" });
{
  DARKS = [];
  const s = pres.addSlide({ masterName: "CAUSA_TITLE", sectionTitle: "Opening" });
  T(s, "CAUSA", 0.8, 1.55, 7, 1.6, { fontSize: 96, bold: true, valign: "middle", charSpacing: -2 });
  T(s, "A Compiler for Explainable and Counterfactual Programming", 0.8, 3.25, 6.6, 1.2, { fontSize: 24, color: MUTED });
  T(s, "Compiler Design Project  ·  Final Review", 0.8, 4.6, 6.6, 0.4, { fontSize: 18 });
  T(s, [
    { text: "[Student name]   ·   [Registration number]", options: { breakLine: true } },
    { text: "[School / University]", options: { breakLine: true } },
    { text: "Guide: [Faculty guide name]" },
  ], 0.8, 5.25, 6.6, 1.2, { fontSize: 15, color: MUTED, paraSpaceAfter: 4 });

  // motif: a real fragment of the pricing dependency graph
  panel(s, 7.9, 1.25, 4.85, 4.9);
  T(s, "pricing.cau  ·  dependency fragment", 8.15, 1.4, 4.4, 0.3, { fontSize: 11, color: MUTED, bold: true });
  const nx = [8.15, 9.7, 11.25], nw = 1.35, nh = 0.62;
  const P = { price: [nx[0], 2.1], discount: [nx[0], 3.3], savings: [nx[1], 2.1], subtotal: [nx[2], 2.1], total: [nx[2], 3.9] };
  const ctr = (k, side) => (side === "r" ? [P[k][0] + nw, P[k][1] + nh / 2] : side === "l" ? [P[k][0], P[k][1] + nh / 2] : [P[k][0] + nw / 2, P[k][1] + nh]);
  const E = [["price", "savings"], ["discount", "savings"], ["savings", "subtotal"]];
  E.forEach(([a, b]) => { const p = ctr(a, "r"), q = ctr(b, "l"); arrow(s, p[0], p[1], q[0], q[1], MUTED, 1.5); });
  arrow(s, ctr("subtotal", "b")[0], ctr("subtotal", "b")[1], P.total[0] + nw / 2, P.total[1], MUTED, 1.5);
  node(s, ...P.price, nw, nh, "price", GREEN);
  node(s, ...P.discount, nw, nh, "discount", GREEN);
  node(s, ...P.savings, nw, nh, "savings", BLUE);
  node(s, ...P.subtotal, nw, nh, "subtotal", BLUE);
  node(s, ...P.total, nw, nh, "total", CYAN, null, "1F3447");
  T(s, [{ text: "$ ./pricing", options: { color: MUTED, breakLine: true } }, { text: "total = 88.375", options: { color: CYAN, bold: true } }],
    8.15, 4.95, 4.4, 0.9, { fontFace: MONO, fontSize: 15 });
  s.addNotes(
    "Opening (about 20 seconds). CAUSA is a custom programming language and a compiler written from scratch, in which the dependencies between computed values are a language feature. A CAUSA program can explain how a value was derived, list what depends on an input, and evaluate hypothetical inputs without disturbing the real results. The motif on the right is a real fragment of the pricing example used throughout the talk.\n\nPlaceholders: replace the name, registration number, school and guide on this slide; they are deliberately not filled in because they cannot be verified from the repository.\n\nLikely question: 'Is this a library?' No. It is its own language with a lexer, parser, semantic analysis, intermediate representation, optimizer and C backend."
  );
}

// =====================================================================
// 2. Problem
// =====================================================================
pres.addSection({ title: "Problem and idea" });
{
  const s = contentSlide("Problem and idea", "A result appears. Its reasoning does not",
    "The problem in under 20 seconds. A program computes a number such as a total price. To understand it, you normally read the code and trace values by hand. Three questions come up all the time: why did this result occur, what depends on this input, and what changes if this value changes. In most workflows each answer means manual tracing, print statements, or editing and rerunning.\n\nTransition: so what would it look like if the language itself answered these questions?\n\nLikely question: 'Debuggers already do this.' Debuggers show execution state; CAUSA answers these questions about the program's dependency structure as language operations, and it can run the hypothetical without touching the real result.");
  // abstract opaque code block -> result
  panel(s, 0.6, 1.55, 4.6, 2.2);
  [0.35, 0.7, 1.05, 1.4, 1.75].forEach((dy, i) => {
    const widths = [3.2, 2.6, 3.5, 2.1, 2.9];
    s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 1.55 + dy, w: widths[i], h: 0.14, rectRadius: 0.05, fill: { color: LINE }, line: { color: LINE, width: 0 }, objectName: oid("bar") });
  });
  T(s, "program", 0.9, 1.62 - 0.05, 2, 0.25, { fontSize: 11, color: MUTED, bold: true });
  arrow(s, 5.3, 2.65, 6.6, 2.65, ACC, 2.5);
  panel(s, 6.7, 1.55, 3.7, 2.2);
  T(s, "total", 6.95, 1.8, 3.2, 0.4, { fontFace: MONO, fontSize: 18, color: MUTED });
  T(s, "88.375", 6.95, 2.3, 3.2, 0.9, { fontFace: MONO, fontSize: 48, bold: true, color: TXT });
  T(s, "?", 10.75, 1.45, 1.8, 2.4, { fontSize: 120, bold: true, color: ACC, align: "center", valign: "middle" });
  // three questions
  const Q = [["Why did this result occur?", "explain"], ["What depends on this input?", "impact"], ["What changes if this value changes?", "whatif"]];
  Q.forEach(([q, op], i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 4.3, 3.93, 2.2);
    T(s, String(i + 1), x + 0.3, 4.5, 0.6, 0.8, { fontSize: 40, bold: true, color: ACC });
    T(s, q, x + 0.3, 5.3, 3.4, 0.85, { fontSize: 20, bold: true, color: TXT });
  });
}

// =====================================================================
// 3. Motivation and objectives
// =====================================================================
{
  const s = contentSlide("Problem and idea", "Objectives: dependencies as a language feature",
    "Motivation versus delivery. The motivation is that understanding a computed value usually costs manual tracing. The five objectives follow from that, and every one is implemented in version 1; the tag at the bottom of each card names where it lives in the repository. 'Implemented' here means built and covered by automated tests, not planned.\n\nTransition: before the design, a quick comparison with how this is done today.\n\nLikely question: 'What is out of scope?' Conditionals, loops, functions, recursion, mutation, strings and collections are deferred (language specification section 13); version 1 is deliberately small so the dependency semantics can be precise.");
  T(s, [{ text: "Motivation  ", options: { bold: true, color: ACC } }, { text: "Understanding a computed value usually means tracing code by hand." }], 0.6, 1.4, 12.1, 0.4, { fontSize: 18 });
  const O = [
    ["Source-level dependency awareness", "Each binding records the names its expression uses.", "semantic.py · ir.py"],
    ["Explainable calculations", "explain prints a derivation tree with values and source expressions.", "runtime: causa_explain"],
    ["Impact analysis", "impact lists direct and all dependents, known statically.", "runtime: causa_impact"],
    ["Isolated what-ifs", "whatif recomputes in a separate environment; real values stay.", "runtime: causa_whatif"],
    ["Native executables", "A Python compiler emits C99; a system C compiler builds the program.", "codegen.py · runtime"],
  ];
  O.forEach(([h, d, tag], i) => {
    const x = 0.6 + i * 2.45, w = 2.3;
    card(s, x, 2.1, w, 4.4);
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.25, y: 2.35, w: 0.55, h: 0.55, fill: { color: PAPER }, line: { color: ACC, width: 1.5 }, objectName: oid("badge") });
    T(s, String(i + 1), x + 0.25, 2.35, 0.55, 0.55, { fontSize: 18, bold: true, color: ACC, align: "center", valign: "middle" });
    T(s, h, x + 0.25, 3.15, w - 0.5, 1.1, { fontSize: 18, bold: true });
    T(s, d, x + 0.25, 4.3, w - 0.5, 1.35, { fontSize: 14, color: GREY });
    chip(s, "✓ Implemented", x + 0.25, 5.65, 1.5, 0.3, TEAL, { fontSize: 11 });
    T(s, tag, x + 0.25, 6.05, w - 0.4, 0.3, { fontFace: MONO, fontSize: 11, color: MUTED });
  });
}

// =====================================================================
// 4. Existing approach vs CAUSA
// =====================================================================
{
  const s = contentSlide("Problem and idea", "Manual tracing vs built-in operations",
    "A fair comparison. Conventional languages and tools can answer all of these questions: with a debugger, with print statements, with IDE navigation, or by editing and rerunning. The difference is that in CAUSA each question is a statement in the language, answered by the runtime from compile-time dependency information. The last row matters for a compiler project: the optimizer is required to leave the binding-level dependency graph unchanged, and a verification pass re-derives the graph after optimization and fails the compile if it differs.\n\nLikely question: 'Is CAUSA better than a debugger?' It is not a replacement. It makes these specific questions cheap and repeatable, and it is a small language, not a general-purpose one.");
  const rows = [
    ["Understand a derivation", "Read the code; add prints or step through a debugger", "explain total", "a derivation tree with values and source expressions"],
    ["Find downstream effects", "Search for uses by hand or with editor tooling", "impact price", "direct and all dependent bindings"],
    ["Try a changed input", "Edit the value, rerun, compare outputs", "whatif price = 160", "before → after; original values untouched"],
    ["Keep dependencies through optimization", "Depends on the tool; not a language guarantee", "verified optimizer", "binding-level graph re-checked after optimization"],
  ];
  T(s, "Conventional workflow", 3.9, 1.45, 4.2, 0.4, { fontSize: 16, bold: true, color: MUTED });
  T(s, "CAUSA", 8.5, 1.45, 4.2, 0.4, { fontSize: 16, bold: true, color: ACC });
  rows.forEach(([dim, conv, op, desc], i) => {
    const y = 1.95 + i * 1.12;
    card(s, 0.6, y, 12.13, 1.0);
    T(s, dim, 0.85, y, 2.9, 1.0, { fontSize: 17, bold: true, valign: "middle" });
    T(s, conv, 3.9, y, 4.2, 1.0, { fontSize: 15, color: MUTED, valign: "middle" });
    T(s, [{ text: op, options: { fontFace: MONO, bold: true, color: VIOLET, fontSize: 15, breakLine: true } }, { text: desc, options: { fontSize: 14, color: TXT } }], 8.5, y, 4.1, 1.0, { valign: "middle" });
  });
  T(s, "Conventional tools can do all of this. CAUSA makes it explicit and built into the language and runtime.", 0.6, 6.5, 12.13, 0.4, { fontSize: 15, color: MUTED });
}

// =====================================================================
// 5. What is CAUSA
// =====================================================================
{
  const s = contentSlide("Problem and idea", "CAUSA: a language and a compiler",
    "What the language looks like. A CAUSA program is a list of inputs and immutable let bindings, each defined from earlier ones, so the dependency structure is a DAG known at compile time. Five statements work on it: show prints a value, explain prints a derivation, impact lists dependents, whatif evaluates hypothetical inputs, and assert checks a condition. Files use the .cau extension. The sample is from the project README: total is 75.0, and the whatif repeats the computation with price = 160.\n\nImportant framing: CAUSA tracks computational dependencies, meaning how values are computed from other values. It does not model real-world causation.\n\nLikely question: 'What types exist?' int, float and bool, with static type checking and declaration-before-use.");
  const ops = [["show", "print a binding's value"], ["explain", "derivation tree for a binding"], ["impact", "direct and all dependents"], ["whatif", "recompute under hypothetical inputs"], ["assert", "check a condition at run time"]];
  ops.forEach(([k, d], i) => {
    const y = 1.6 + i * 0.88;
    card(s, 0.6, y, 5.7, 0.74);
    T(s, k, 0.85, y, 1.5, 0.74, { fontFace: MONO, fontSize: 18, bold: true, color: INK, valign: "middle" });
    T(s, d, 2.4, y, 3.8, 0.74, { fontSize: 15, valign: "middle" });
  });
  codeCard(s, 6.7, 1.6, 6.03, 4.3, "example.cau", highlight(
`input price = 100
input discount = 0.25

let savings = price * discount
let total = price - savings

show total                # total = 75.0
explain total
whatif price = 160 show total
impact price`, 15));
  card(s, 0.6, 6.15, 12.13, 0.7, { line: { color: ACC, width: 1.5 } });
  T(s, "A custom language and compiler (Python → C99 → native executable): not a Python library, not a graph viewer.", 0.85, 6.15, 11.7, 0.7, { fontSize: 15, bold: true, valign: "middle" });
}

// =====================================================================
// 6. Literature survey
// =====================================================================
{
  const s = contentSlide("Problem and idea", "Related work and foundations",
    "A concise literature survey; the full verified bibliography is on the last slide. Four themes. Dependency analysis: Weiser's program slicing and the program dependence graph of Ferrante, Ottenstein and Warren are the classic foundations for asking which statements affect a value. Provenance: the Cheney, Chiticariu and Tan survey, and the Cheney, Ahmed and Acar paper on provenance as dependency analysis, connect dependencies to explanations of results. Explanations and counterfactuals: the Whyline lets programmers ask why-questions about program behavior, and the Karimi et al. 2022 survey covers contrastive and counterfactual explanations. Compilers and testing: LLVM and MLIR are reference intermediate-representation designs, and the compiler-testing survey by Chen et al. and the fuzzing survey preprint by Ma frame how compilers are validated.\n\nClaim discipline: CAUSA uses established ideas. Its contribution is integrating dependency tracking, explanation and counterfactual evaluation into one small language, compiler and runtime workflow. I am not claiming it is the first system of its kind.\n\nRecent sources: Karimi et al. is 2022; the Ma survey is a 2023 arXiv preprint, not peer reviewed.");
  const C = [
    ["Dependency analysis", VIOLET, [["[1] Weiser 1984", "program slicing", "Foundational"], ["[2] Ferrante et al. 1987", "program dependence graph", "Foundational"]], "Which statements affect a value"],
    ["Provenance", TEAL, [["[3] Cheney et al. 2009", "why, how, where provenance", "Directly related"], ["[4] Cheney et al. 2011", "provenance as dependency analysis", "Directly related"]], "Dependencies explain results"],
    ["Explanations and counterfactuals", ORANGE, [["[5] Ko & Myers 2004", "Whyline: “why” questions", "Directly related"], ["[6] Karimi et al. 2022", "counterfactual explanations survey", "Recent · related"]], "Asking why, and what if"],
    ["Compilers and testing", BLUE, [["[7] Lattner & Adve 2004", "LLVM IR"], ["[8] Lattner et al. 2021", "MLIR"], ["[9] Chen et al. 2020", "compiler testing survey"], ["[10] Ma 2023 (preprint)", "compiler fuzzing survey"]], "IR design and validation"],
  ];
  C.forEach(([h, col, refs, rel], i) => {
    const x = 0.6 + i * 3.05, w = 2.92;
    card(s, x, 1.45, w, 4.55);
    T(s, h, x + 0.2, 1.6, w - 0.4, 0.7, { fontSize: 17, bold: true, color: col });
    const lines = [];
    refs.forEach((r, k) => {
      lines.push({ text: r[0], options: { bold: true, fontSize: 16, color: TXT, breakLine: true } });
      lines.push({ text: r[1], options: { fontSize: 14, color: MUTED, breakLine: true } });
      if (r[2]) lines.push({ text: r[2], options: { fontSize: 12, color: r[2].startsWith("Directly") ? CYAN : r[2].startsWith("Recent") ? VIOLET : MUTED, breakLine: k < refs.length - 1 } });
      else if (k < refs.length - 1) lines[lines.length - 1].options.breakLine = true;
      if (k < refs.length - 1) lines.push({ text: " ", options: { fontSize: 10, breakLine: true } });
    });
    T(s, lines, x + 0.2, 2.35, w - 0.4, 3.0, {});
    T(s, rel, x + 0.2, 5.3, w - 0.4, 0.55, { fontSize: 14, color: TXT, valign: "bottom" });
  });
  T(s, "CAUSA builds on established ideas; its contribution is integrating them into one language, compiler and runtime workflow.", 0.6, 6.25, 12.13, 0.6, { fontSize: 16, bold: true });
}

// =====================================================================
// 7. Architecture
// =====================================================================
pres.addSection({ title: "Architecture" });
{
  const s = contentSlide("Architecture", "System architecture",
    "The most important slide. Source code in a .cau file flows through the front end: the lexer produces tokens on demand, the hand-written recursive-descent parser builds the AST, and semantic analysis resolves names and checks types. The middle is the Causal IR, a typed single-assignment graph with stable node IDs and explicit dependency edges, plus a frozen binding-level provenance graph, and the optimizer, which may only make rewrites that leave that graph unchanged. The back end is the C code generator, which emits deterministic C99 together with metadata tables; this is compiled together with the CAUSA runtime by a system C compiler into a native executable.\n\nThe Python compiler performs every step up to and including C generation; it never runs the C compiler itself. The runtime library provides the language's execution operations: explain, impact, whatif and assert, plus checked arithmetic and launch-time --set validation in the runtime header.\n\nLikely question: 'Why does the compiler not call gcc?' It is a documented design decision for the first version; a single build command is listed as a next step.");
  panel(s, 0.45, 1.2, 12.43, 4.95);
  // legend
  [["Front end · Python", CYAN], ["Causal IR and optimizer · Python", VIOLET], ["Back end · C", TEAL]].forEach(([t, c], i) => {
    const x = 0.6 + [0, 2.9, 6.6][i];
    s.addShape(pres.ShapeType.ellipse, { x, y: 1.43, w: 0.16, h: 0.16, fill: { color: c }, line: { color: c, width: 0 }, objectName: oid("dot") });
    T(s, t, x + 0.25, 1.35, 3.6, 0.32, { fontSize: 13, color: MUTED, valign: "middle" });
  });
  const bw = 1.7, bh = 0.85, step = 2.02, x0 = 0.6;
  const r1 = [["CAUSA Source", ".cau", CYAN], ["Lexer", null, CYAN], ["Parser", null, CYAN], ["Abstract Syntax Tree", null, CYAN], ["Semantic Analysis", null, CYAN]];
  const r2 = [["Causal IR", null, VIOLET], ["Optimizer", null, VIOLET], ["C Code Generator", null, TEAL], ["Generated C + Runtime", null, TEAL], ["System C Compiler", null, TEAL], ["Native Executable", null, TEAL]];
  const y1 = 2.0, y2 = 3.75;
  const drawRow = (row, y) => row.forEach(([l, sub, c], i) => {
    const x = x0 + i * step;
    node(s, x, y, bw, bh, l, c, null, SURF2, 13);
    if (i > 0) arrow(s, x - (step - bw) + 0.02, y + bh / 2, x - 0.02, y + bh / 2, MUTED, 1.5);
  });
  drawRow(r1, y1);
  drawRow(r2, y2);
  // elbow from Semantic Analysis down to Causal IR
  const sx = x0 + 4 * step + bw / 2, mid = (y1 + bh + y2) / 2, cx = x0 + bw / 2;
  arrow(s, sx, y1 + bh, sx, mid, MUTED, 1.5, false);
  arrow(s, sx, mid, cx, mid, MUTED, 1.5, false);
  arrow(s, cx, mid, cx, y2, MUTED, 1.5, true);
  // runtime capabilities
  const gx = x0 + 3 * step + bw / 2;
  T(s, "Runtime library", 0.6, 5.45, 1.9, 0.3, { fontSize: 13, bold: true, color: TEAL });
  T(s, "causa_runtime.h / .c", 0.6, 5.75, 1.9, 0.3, { fontFace: MONO, fontSize: 11, color: MUTED });
  arrow(s, gx, y2 + bh, gx, 5.3, TEAL, 1.5, false);
  s.addShape(pres.ShapeType.line, { x: 2.9, y: 5.3, w: gx - 2.9 + 4.6, h: 0, line: { color: TEAL, width: 1.5 }, objectName: oid("rule") });
  const caps = ["explain", "impact", "whatif", "assert", "checked math", "--set check"];
  caps.forEach((c, i) => {
    const x = 2.9 + i * 1.62;
    arrow(s, x + 0.72, 5.3, x + 0.72, 5.55, TEAL, 1.2, false);
    chip(s, c, x, 5.55, 1.45, 0.4, TEAL, { fontFace: MONO, fontSize: 12 });
  });
  T(s, "Dependencies are computed at compile time and embedded as metadata; the executable records values.", 0.6, 6.4, 12.13, 0.4, { fontSize: 15, color: GREY });
}

// =====================================================================
// 8. Pricing example
// =====================================================================
pres.addSection({ title: "Demonstration" });
{
  const s = contentSlide("Demonstration", "Language example: a pricing model",
    "The running example, examples/pricing.cau in the repository. Inputs are price, discount, tax, fee and units; lets compute savings, subtotal and total, plus expensive, per_unit and bulk (not shown on this slide to keep it readable). With the source values: savings is 100 times 0.25, which is 25.0; subtotal is 100 minus 25.0, which is 75.0; total is 75.0 times (1 plus 0.125) plus 4, which is 88.375. per_unit is 88.375 divided by 4, which is 22.09375, and expensive and bulk are both true. These values are the program's real output, checked against the documentation.\n\nTransition: the same program as a dependency graph.\n\nLikely question: 'Why does 100 print as 100 but 25.0 as 25.0?' Types are inferred from literals; price is an int and savings is a float, and the runtime prints floats like Python's repr.");
  panel(s, 6.85, 1.35, 5.88, 4.95);
  codeCard(s, 0.6, 1.5, 5.9, 4.7, "pricing.cau (excerpt)", highlight(
`input price = 100
input discount = 0.25
input tax = 0.125
input fee = 4

let savings = price * discount
let subtotal = price - savings
let total = subtotal * (1 + tax) + fee

show total`, 16));
  // calculation chain
  const steps = [["price", "100", "input", GREEN], ["savings", "25.0", "price * discount", BLUE], ["subtotal", "75.0", "price - savings", BLUE], ["total", "88.375", "subtotal * (1 + tax) + fee", CYAN]];
  steps.forEach(([nm, val, f, c], i) => {
    const y = 1.5 + i * 1.22;
    card(s, 7.0, y, 5.73, 1.0, { line: { color: c, width: 1.5 } });
    T(s, nm, 7.25, y + 0.1, 2.0, 0.4, { fontFace: MONO, fontSize: 16, bold: true, color: c });
    T(s, f, 7.25, y + 0.55, 3.4, 0.35, { fontFace: MONO, fontSize: 12, color: MUTED });
    T(s, val, 9.9, y, 2.6, 1.0, { fontFace: MONO, fontSize: 30, bold: true, align: "right", valign: "middle" });
    if (i < 3) arrow(s, 9.85, y + 1.0, 9.85, y + 1.22, MUTED, 1.5);
  });
  T(s, "100  →  25.0 savings  →  75.0 subtotal  →  88.375 total", 0.6, 6.4, 12.13, 0.4, { fontFace: MONO, fontSize: 16, color: ACC, bold: true });
}

// =====================================================================
// 9. Dependency graph
// =====================================================================
{
  const s = contentSlide("Demonstration", "The dependency graph: 11 bindings, 11 edges",
    "The same program as a graph. Green nodes are inputs; blue nodes are let bindings. Each column is a step deeper in the DAG. Arrows here point from a binding to the bindings that use it, which matches how CAUSA Studio draws it. Be careful with direction: the compiler stores the canonical edges the other way round, each binding pointing to the names it uses, and derives the reverse direction for impact. The edges are: price and discount into savings; price and savings into subtotal; subtotal, tax and fee into total; total into expensive; total and units into per_unit; per_unit into bulk. That is 11 edges, matching the count Studio reports.\n\nKey point in the note on the slide: dependencies come from the source expressions, not from the current numbers. So x * 0 still depends on x.\n\nLikely question: 'Are there cycles?' No. Each binding can only use earlier ones, so the graph is acyclic by construction.");
  panel(s, 0.45, 1.35, 12.43, 4.95);
  const w = 1.45, h = 0.62;
  const colx2 = [0, 1, 2, 3, 4, 5].map((i) => 0.6 + i * ((12.13 - w) / 5));
  const Y0 = 1.55;
  const pos = {
    price: [colx2[0], Y0 + 0.0], discount: [colx2[0], Y0 + 0.9], tax: [colx2[0], Y0 + 1.8], fee: [colx2[0], Y0 + 2.7], units: [colx2[0], Y0 + 3.6],
    savings: [colx2[1], Y0 + 0.9], subtotal: [colx2[2], Y0 + 0.2], total: [colx2[3], Y0 + 1.9],
    expensive: [colx2[4], Y0 + 1.1], per_unit: [colx2[4], Y0 + 2.7], bulk: [colx2[5], Y0 + 2.7],
  };
  const type = { price: "int", discount: "float", tax: "float", fee: "int", units: "int", savings: "float", subtotal: "float", total: "float", expensive: "bool", per_unit: "float", bulk: "bool" };
  const inputs = new Set(["price", "discount", "tax", "fee", "units"]);
  const edges = [["price", "savings"], ["discount", "savings"], ["price", "subtotal"], ["savings", "subtotal"], ["tax", "total"], ["fee", "total"], ["subtotal", "total"], ["total", "expensive"], ["units", "per_unit"], ["total", "per_unit"], ["per_unit", "bulk"]];
  edges.forEach(([a, b]) => {
    const ca = [pos[a][0] + w, pos[a][1] + h / 2], cb = [pos[b][0], pos[b][1] + h / 2];
    arrow(s, ca[0], ca[1], cb[0], cb[1], "5B6B7B", 1.5);
  });
  Object.keys(pos).forEach((k) => node(s, pos[k][0], pos[k][1], w, h, k, inputs.has(k) ? GREEN : BLUE, `${inputs.has(k) ? "input" : "let"} · ${type[k]}`, SURF2, 15));
  // legend
  [["input", GREEN], ["let (computed)", BLUE]].forEach(([t, c], i) => {
    s.addShape(pres.ShapeType.roundRect, { x: 0.6 + i * 1.9, y: 6.0, w: 0.3, h: 0.22, rectRadius: 0.04, fill: { color: SURF2 }, line: { color: c, width: 1.5 }, objectName: oid("key") });
    T(s, t, 1.0 + i * 1.9, 5.94, 1.7, 0.34, { fontSize: 13, color: MUTED, valign: "middle" });
  });
  T(s, "Arrow: a value flows from a binding to the bindings that use it. The compiler stores the reverse (binding → names it uses).", 4.5, 5.95, 8.2, 0.35, { fontSize: 11, color: MUTED });
  card(s, 0.6, 6.42, 12.13, 0.5, { line: { color: ACC, width: 1.5 } });
  T(s, "Dependencies are derived from source expressions, not from whether the current numerical output changes.", 0.85, 6.42, 11.7, 0.5, { fontSize: 15, bold: true, valign: "middle" });
}

// =====================================================================
// 10. Explain
// =====================================================================
{
  const s = contentSlide("Demonstration", "explain: why did this value occur?",
    "explain answers 'how was this derived?'. The statement is explain total, run in the compiled pricing program; the output on the left is real runtime output, identical to the documented expected output. It is a pre-order tree: each binding with its value and its source expression, children in order of first appearance, and a shared input such as price is expanded once and marked 'see above' the second time. Below the tree are four summary lists: direct dependencies, transitive dependencies, inputs, and intermediates.\n\nThe tree is built from source-level metadata and the recorded base values. It never reads the optimized node graph, which is why optimization cannot change an explanation.\n\nLikely question: 'Does explain re-run the program?' No. It reads the compile-time dependency tables and the values recorded during execution.");
  codeCard(s, 0.6, 1.5, 7.2, 5.0, "$ ./build/pricing      (output of  explain total)", consoleRuns([
    ["explain total", VIOLET],
    ["  total = 88.375  [let: subtotal * (1 + tax) + fee]", TXT],
    ["    subtotal = 75.0  [let: price - savings]", TXT],
    ["      price = 100  [input]", GREEN],
    ["      savings = 25.0  [let: price * discount]", TXT],
    ["        price = 100  [input, see above]", GREEN],
    ["        discount = 0.25  [input]", GREEN],
    ["    tax = 0.125  [input]", GREEN],
    ["    fee = 4  [input]", GREEN],
    ["  direct dependencies: tax, fee, subtotal", MUTED],
    ["  transitive dependencies: price, discount, tax,", MUTED],
    ["      fee, savings, subtotal", MUTED],
    ["  inputs: price, discount, tax, fee", MUTED],
    ["  intermediates: savings, subtotal", MUTED],
  ], 14));
  // small relationship diagram
  panel(s, 8.1, 1.4, 4.63, 5.1);
  T(s, "depends on", 8.3, 1.5, 2, 0.3, { fontSize: 12, color: MUTED, bold: true });
  const nw = 1.3, nh = 0.55;
  const N = { total: [9.85, 1.95, BLUE], subtotal: [8.4, 3.1, BLUE], tax: [9.95, 3.1, GREEN], fee: [11.4, 3.1, GREEN],
              price1: [8.3, 4.3, GREEN], savings: [9.9, 4.3, BLUE], price2: [9.1, 5.45, GREEN], discount: [10.7, 5.45, GREEN] };
  const lab = (k) => k.replace(/[12]$/, "");
  const dep = [["total", "subtotal"], ["total", "tax"], ["total", "fee"], ["subtotal", "price1"], ["subtotal", "savings"], ["savings", "price2"], ["savings", "discount"]];
  dep.forEach(([a, b]) => arrow(s, N[a][0] + nw / 2, N[a][1] + nh, N[b][0] + nw / 2, N[b][1], "5B6B7B", 1.4));
  Object.keys(N).forEach((k) => node(s, N[k][0], N[k][1], nw, nh, lab(k), N[k][2], null, SURF2, 14));
  T(s, "Each arrow: “uses”. price is reached twice; the runtime prints it once and marks it “see above”.", 8.3, 6.0, 4.3, 0.45, { fontSize: 12, color: MUTED });
}

// =====================================================================
// 11. Impact
// =====================================================================
{
  const s = contentSlide("Demonstration", "impact: what else changes?",
    "impact answers 'what depends on this?'. For impact discount, the direct dependent is just savings, because only savings mentions discount. The full affected set is six bindings, because savings feeds subtotal, which feeds total, which feeds expensive and per_unit, which feeds bulk. The text on the left is the real runtime output. The labels the runtime prints are 'direct dependents' and 'all dependents'; Studio shows the same lists as 'direct' and 'all affected'.\n\nImpact is static. It reads only the compile-time dependency tables and never reads values, so it is instant and cannot fail. Compare with whatif, which actually recomputes.\n\nLikely question: 'Is impact the reverse of explain?' Yes, in direction: explain walks backward from a binding to what it uses; impact walks forward to what uses it.");
  codeCard(s, 0.6, 1.5, 6.3, 2.3, "output of  impact discount", consoleRuns([
    ["impact discount", VIOLET],
    ["  direct dependents: savings", ORANGE],
    ["  all dependents: savings, subtotal, total,", TXT],
    ["      expensive, per_unit, bulk", TXT],
  ], 15));
  card(s, 7.2, 1.5, 5.53, 2.3);
  T(s, "Two answers", 7.45, 1.62, 5, 0.35, { fontSize: 18, bold: true });
  T(s, [
    { text: "direct: ", options: { bold: true, color: ORANGE } },
    { text: "bindings whose expression mentions discount", options: { breakLine: true } },
    { text: "all: ", options: { bold: true, color: ORANGE } },
    { text: "those plus everything downstream of them" },
  ], 7.45, 2.1, 5.05, 1.6, { fontSize: 16, paraSpaceAfter: 8 });
  panel(s, 0.45, 3.95, 12.43, 2.15);
  const ny = 4.45, nw2 = 1.5, nh2 = 0.62;
  const X = [0.6, 2.75, 4.9, 7.05, 9.2, 11.23];
  const P = { discount: [X[0], ny + 0.35], savings: [X[1], ny + 0.35], subtotal: [X[2], ny + 0.35], total: [X[3], ny + 0.35], expensive: [X[4], ny - 0.15], per_unit: [X[4], ny + 0.85], bulk: [X[5], ny + 0.85] };
  const E = [["discount", "savings"], ["savings", "subtotal"], ["subtotal", "total"], ["total", "expensive"], ["total", "per_unit"], ["per_unit", "bulk"]];
  E.forEach(([a2, b2]) => arrow(s, P[a2][0] + nw2, P[a2][1] + nh2 / 2, P[b2][0], P[b2][1] + nh2 / 2, ORANGE, 1.5));
  Object.keys(P).forEach((k) => {
    if (k === "discount") node(s, ...P[k], nw2, nh2, k, GREEN, null, SURF2, 14);
    else if (k === "savings") node(s, ...P[k], nw2, nh2, k, ORANGE, null, "5A3414", 14);
    else node(s, ...P[k], nw2, nh2, k, ORANGE, null, SURF2, 14);
  });
  chip(s, "direct dependent", P.savings[0] - 0.1, P.savings[1] - 0.5, 1.7, 0.32, ORANGE, { fontSize: 12 });
  T(s, "all affected: savings, subtotal, total, expensive, per_unit, bulk", 0.7, 4.02, 8, 0.3, { fontSize: 14, color: MUTED });
  T(s, "Static: read from compile-time dependency tables. No values are recomputed.", 0.6, 6.3, 12.13, 0.5, { fontSize: 16, bold: true });
}

// =====================================================================
// 12. What-if
// =====================================================================
{
  const s = contentSlide("Demonstration", "whatif: counterfactual execution",
    "whatif answers 'what if this input were different?'. Left is the baseline with price 100; right is the counterfactual with price 150, from CAUSA Studio's What-if panel, which runs the real runtime. savings becomes 37.5, subtotal 112.5, total 130.5625, and per_unit 32.640625; expensive stays true, and bulk flips from true to false. The table marks the override, changed values, and unchanged values.\n\nHow it works: the runtime copies the base values into a separate counterfactual environment, writes the overrides there, and re-evaluates only the dependency cone of the overridden inputs. The original execution state is never written; in the pricing demo, the final 'show total' after five whatif statements still prints 88.375.\n\nLaunch-time inputs are different: ./pricing --set price=150 --set discount=0.3 changes the real inputs before anything runs (total becomes 122.125) and every statement, including each whatif's before values, sees them. Invalid arguments are rejected before any output.\n\nLikely question: 'What if a hypothetical fails?' A failure such as division by zero is reported as an error outcome, dependents are marked unavailable, and the program continues.");
  // baseline vs counterfactual
  const rows = [["price", "100", "150", "override"], ["savings", "25.0", "37.5", "changed"], ["subtotal", "75.0", "112.5", "changed"], ["total", "88.375", "130.5625", "changed"], ["expensive", "true", "true", "same"], ["per_unit", "22.09375", "32.640625", "changed"], ["bulk", "true", "false", "changed"]];
  panel(s, 0.6, 1.5, 7.4, 4.1);
  T(s, "binding", 0.9, 1.65, 2, 0.3, { fontSize: 12, color: MUTED, bold: true });
  T(s, "baseline", 3.0, 1.65, 1.8, 0.3, { fontSize: 12, color: MUTED, bold: true });
  T(s, "whatif price = 150", 5.0, 1.65, 2, 0.3, { fontSize: 12, color: CYAN, bold: true });
  rows.forEach(([b, a, c, st], i) => {
    const y = 2.1 + i * 0.5;
    const col = st === "override" ? ORANGE : st === "changed" ? BLUE : MUTED;
    T(s, b, 0.9, y, 2, 0.4, { fontFace: MONO, fontSize: 15, color: col, valign: "middle", bold: st !== "same" });
    T(s, a, 3.0, y, 1.8, 0.4, { fontFace: MONO, fontSize: 15, valign: "middle" });
    T(s, c, 5.0, y, 1.9, 0.4, { fontFace: MONO, fontSize: 15, valign: "middle", bold: true, color: st === "same" ? MUTED : TXT });
    arrow(s, 4.55, y + 0.2, 4.85, y + 0.2, MUTED, 1.2);
  });
  // right: isolation and launch-time
  card(s, 8.3, 1.5, 4.43, 2.0);
  T(s, "Isolated", 8.55, 1.62, 4, 0.35, { fontSize: 17, bold: true, color: ACC });
  T(s, "A separate environment is recomputed; the real execution is never written. After five whatif statements, show total still prints 88.375.", 8.55, 2.0, 3.95, 1.45, { fontSize: 14, color: TXT });
  codeCard(s, 8.3, 3.7, 4.43, 1.9, "launch-time inputs", consoleRuns([
    ["$ ./build/pricing \\", MUTED],
    ["    --set price=150 \\", TXT],
    ["    --set discount=0.3", TXT],
    ["total = 122.125", CYAN],
  ], 13));
  T(s, "Source: values from the real runtime, shown in CAUSA Studio's What-if panel; launch output from docs/demonstration.md.", 0.6, 5.85, 12.13, 0.35, { fontSize: 12, color: MUTED });
  T(s, "changed input → affected calculations recomputed → resulting output", 0.6, 6.35, 12.13, 0.4, { fontSize: 16, bold: true, color: ACC });
}

// =====================================================================
// 13. Causal IR and optimization
// =====================================================================
pres.addSection({ title: "Internals and Studio" });
{
  const s = contentSlide("Internals and Studio", "Causal IR: optimization without losing dependencies",
    "Technical depth. The Causal IR is a typed, single-assignment graph: input, const, op and bind nodes with stable IDs, explicit operand edges, and source locations. A bind node anchors each let so explain, whatif and impact can refer to source-level bindings even if the operations under them are merged. On the left is the real IR for a one-line program: note the explicit itof nodes where an int is promoted to float.\n\nThe optimizer may do three things: constant folding when it cannot raise a runtime error, common-subexpression elimination within one binding, and removal of dead constants. It must never remove an input or a bind, never rewrite away a reference to a binding, and never reorder anything that can fail. After optimizing, a verification pass re-derives the binding-level graph and requires it to equal the original; a mismatch is an internal compiler error.\n\nThe x * 0 example illustrates the invariant, and it is also real behaviour: I ran the optimizer on a program with let y = x * 0 and let z = x - x; it reported no changes and both y and z still depend on x. On pricing.cau the optimizer folds two integer-to-float conversions and removes two constants, taking the IR from 30 to 28 nodes.\n\nLikely question: 'Why not simplify x * 0 to 0?' Because the value 0 hides that y depends on x, and explain and impact would be wrong.");
  codeCard(s, 0.6, 1.5, 4.6, 4.75, "Causal IR  (price * (1 - discount))", consoleRuns([
    ["n0 = input     int    price", GREEN],
    ["n1 = input     float  discount", GREEN],
    ["n2 = const     int    1", TXT],
    ["n3 = itof      n2", VIOLET],
    ["n4 = sub       n3, n1", TXT],
    ["n5 = itof      n0", VIOLET],
    ["n6 = mul       n5, n4", TXT],
    ["n7 = bind      n6     total", CYAN],
    ["", TXT],
    ["total → price, discount", MUTED],
  ], 13));
  // middle: rules
  card(s, 5.45, 1.5, 3.55, 4.75);
  T(s, "Optimizer", 5.7, 1.62, 3, 0.35, { fontSize: 17, bold: true, color: VIOLET });
  T(s, [
    { text: "Allowed", options: { bold: true, color: TEAL, breakLine: true } },
    { text: "fold constants that cannot fail", options: { bullet: true, breakLine: true } },
    { text: "merge duplicates in one binding", options: { bullet: true, breakLine: true } },
    { text: "remove dead constants", options: { bullet: true, breakLine: true } },
    { text: " ", options: { fontSize: 6, breakLine: true } },
    { text: "Never", options: { bold: true, color: RED, breakLine: true } },
    { text: "drop an input or binding", options: { bullet: true, breakLine: true } },
    { text: "remove a reference to a binding", options: { bullet: true, breakLine: true } },
    { text: "fold 1 / 0 or an overflow", options: { bullet: true } },
  ], 5.7, 2.05, 3.1, 3.0, { fontSize: 14, paraSpaceAfter: 4 });
  T(s, "pricing.cau: 30 → 28 nodes", 5.7, 5.7, 3.1, 0.4, { fontSize: 13, color: MUTED });
  // right: invariant
  panel(s, 9.25, 1.5, 3.48, 4.75, { line: { color: ORANGE, width: 1.5 } });
  T(s, "Design invariant", 9.5, 1.62, 3, 0.35, { fontSize: 17, bold: true, color: ORANGE });
  T(s, highlight("let y = x * 0\nlet z = x - x", 14), 9.5, 2.1, 3.0, 0.8, {});
  T(s, "A numeric simplifier would turn both into 0 and erase the edge to x.", 9.5, 3.0, 3.0, 0.9, { fontSize: 14 });
  T(s, "CAUSA keeps it:", 9.5, 3.95, 3.0, 0.3, { fontSize: 14, bold: true });
  T(s, consoleRuns([["y: let → x", GREEN], ["z: let → x", GREEN], ["optimizer: no changes", MUTED]], 13), 9.5, 4.3, 3.0, 0.95, {});
  T(s, "Illustrates the invariant; checked by running the compiler.", 9.5, 5.5, 3.0, 0.6, { fontSize: 11, color: MUTED });
  T(s, "After optimizing, the binding-level graph is re-derived and must equal the original.", 0.6, 6.4, 12.13, 0.4, { fontSize: 15, bold: true });
}

// =====================================================================
// 14. Code generation and runtime
// =====================================================================
{
  const s = contentSlide("Internals and Studio", "Code generation and the runtime",
    "From IR to a program. The generator emits one deterministic C99 file: one case per IR node in a switch, metadata tables describing nodes, bindings and dependencies, and a main that runs the program's steps in order. Integers map to int64_t with overflow checked before computing, so there is no signed-overflow undefined behaviour; floats map to double, and float literals are emitted as exact hexadecimal constants so the C compiler does no decimal rounding. Division by zero and non-finite results become runtime errors R101 to R103 reported at the operator's source location.\n\nThe runtime library, causa_runtime.c, uses only the C standard library. It formats values the way Python's repr does, and implements explain, impact, whatif and assert from the metadata tables. The system C compiler then builds generated C plus runtime into the native executable.\n\nWhy C? It gives a real native executable with little machinery, a stable target, and lets the runtime be small and testable. Likely question: 'Why is gcc -O2 so slow in the benchmark?' The generated file has one switch case per IR node, which -O2 optimizes slowly; see the evaluation slide.");
  panel(s, 0.45, 1.3, 12.43, 1.0);
  const flow = [["CAUSA", CYAN], ["C source", TEAL], ["C runtime + system compiler", TEAL], ["native executable", TEAL]];
  const fw = [1.7, 1.9, 3.4, 2.3];
  let fx = 0.6;
  flow.forEach(([t, c], i) => {
    node(s, fx, 1.5, fw[i], 0.7, t, c, null, SURF2, 14);
    if (i < 3) arrow(s, fx + fw[i] + 0.04, 1.85, fx + fw[i] + 0.36, 1.85, MUTED, 1.5);
    fx += fw[i] + 0.4;
  });
  codeCard(s, 0.6, 2.55, 7.4, 3.75, "generated C (excerpt of pricing.c)", consoleRuns([
    ["case 6: /* n6 op mul @10:21 owner savings */", MUTED],
    ["  return causa_check(", TXT],
    ["      causa_mul_f64(env[5].f, env[1].f, &env[6].f),", TXT],
    ["      10, 21, err);", TXT],
    ["case 7: /* n7 bind savings: price * discount */", MUTED],
    ["  env[7] = env[6];", TXT],
    ["  return CAUSA_OK;", TXT],
    ["", TXT],
    ["causa_configure(argc, argv);   /* --set NAME=VALUE */", MUTED],
    ["causa_explain(env, CAUSA_BINDING_total);", CYAN],
  ], 13));
  const pts = [["Checked arithmetic", "overflow detected before computing; R101–R103 report the operator’s line and column"], ["Exact floats", "literals emitted as hex floating constants; no decimal rounding in the C compiler"], ["Small runtime", "explain, impact, whatif, assert from metadata tables; standard C library only"]];
  pts.forEach(([h, d], i) => {
    const y = 2.55 + i * 1.28;
    card(s, 8.3, y, 4.43, 1.15);
    T(s, h, 8.5, y + 0.1, 4.0, 0.35, { fontSize: 16, bold: true, color: TEAL });
    T(s, d, 8.5, y + 0.48, 4.05, 0.65, { fontSize: 13, color: MUTED });
  });
  T(s, "Build:  gcc -std=c99 -I causa/runtime pricing.c causa/runtime/causa_runtime.c -o pricing -lm", 0.6, 6.5, 12.13, 0.35, { fontFace: MONO, fontSize: 12, color: GREY });
}

// =====================================================================
// 15. CAUSA Studio
// =====================================================================
{
  const s = contentSlide("Internals and Studio", "CAUSA Studio: the desktop application",
    "CAUSA Studio is a desktop application, written in Tkinter with only the standard library, that drives the real compiler and runtime: a source editor with highlighting and live diagnostics, an integrated console, the dependency graph, and Explain, Impact and What-if tabs. Studio has no CAUSA semantics of its own; for Explain, Impact and What-if it builds a small query program, compiles it with the real compiler and runs it with the real runtime.\n\nThe screenshots are genuine captures of the running application, taken by a script (presentation/capture_studio.py) that drives the real window. They were captured on Linux under a virtual display with Python 3.12, Tk and GCC 13.3 because that is what was available when building the deck; the project's documented validated environment is Windows 11. Replace them with Windows captures if you prefer. The pricing example shows 5 inputs, 6 lets and 11 edges, as the caption in the Graph tab states.\n\nCallouts: 1 source editor, 2 integrated console, 3 dependency graph, 4 analysis tabs, 5 build and runtime status.\n\nLikely question: 'Can Studio change values at launch?' Not yet; the What-if panel covers hypothetical inputs and launch values are a command-line feature.");
  const iw = 7.9, ih = iw * 1161 / 2064;
  s.addImage({ path: path.join(ASSETS, "studio_graph.png"), x: 0.6, y: 1.45, w: iw, h: ih, objectName: "studio-screenshot", altText: "CAUSA Studio window showing the pricing example: editor, console and dependency graph" });
  const marks = [[1, 0.17, 0.35], [2, 0.17, 0.78], [3, 0.62, 0.16], [4, 0.6, 0.055], [5, 0.62, 0.975]];
  marks.forEach(([k, fx, fy]) => {
    const cx = 0.6 + iw * fx, cy = 1.45 + ih * fy;
    s.addShape(pres.ShapeType.ellipse, { x: cx - 0.14, y: cy - 0.14, w: 0.28, h: 0.28, fill: { color: ACC }, line: { color: "FFFFFF", width: 1 }, objectName: oid("callout") });
    T(s, String(k), cx - 0.14, cy - 0.14, 0.28, 0.28, { fontSize: 11, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  });
  // crops
  const cw = 4.0, wh = cw * 415 / 1029, gh = cw * 375 / 1319, c2 = 2.4, ch = c2 * 470 / 745;
  s.addImage({ path: path.join(ASSETS, "crop_whatif.png"), x: 8.73, y: 1.45, w: cw, h: wh, objectName: "studio-whatif", altText: "Studio What-if panel with price changed to 150" });
  s.addImage({ path: path.join(ASSETS, "crop_graph.png"), x: 8.73, y: 1.45 + wh + 0.15, w: cw, h: gh, objectName: "studio-graph", altText: "Studio dependency graph" });
  s.addImage({ path: path.join(ASSETS, "crop_console.png"), x: 8.73, y: 1.45 + wh + gh + 0.3, w: c2, h: ch, objectName: "studio-console", altText: "Studio console showing formatted impact and show output" });
  const L = ["Source editor", "Integrated console", "Dependency graph", "Analysis tabs", "Build / runtime status"];
  L.forEach((t, i) => {
    const x = 0.6 + (i % 5) * 2.43;
    s.addShape(pres.ShapeType.ellipse, { x, y: 6.1, w: 0.24, h: 0.24, fill: { color: ACC }, line: { color: ACC, width: 0 }, objectName: oid("key") });
    T(s, String(i + 1), x, 6.1, 0.24, 0.24, { fontSize: 10, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
    T(s, t, x + 0.32, 6.05, 2.0, 0.34, { fontSize: 13, valign: "middle" });
  });
  T(s, "Real application screenshots, captured by presentation/capture_studio.py (Linux, Xvfb, Python 3.12). Pricing example: 5 inputs · 6 lets · 11 edges.", 0.6, 6.5, 12.13, 0.4, { fontSize: 11, color: MUTED });
}

// =====================================================================
// 16. Testing and validation
// =====================================================================
pres.addSection({ title: "Evaluation" });
{
  const s = contentSlide("Evaluation", "Testing and validation",
    "Headline: 205 automated tests passed, with none skipped, in the recorded full run on Windows 11 with Python 3.11.9 and MSYS2 UCRT64 GCC 16.1.0. The test suite in the repository today has 257 tests: those 205 compiler, runtime and demo tests plus 52 CAUSA Studio tests (service, formatting and window tests). I counted both from the repository; the 205 pass figure is the recorded Windows result, and I did not re-run Windows here.\n\nWhat the tests check, from the README: every specification runtime case is built and its stdout, stderr and exit status compared byte for byte; every shell command in docs/demonstration.md is executed and its output compared; float formatting is compared with Python's repr on 35,000 values on every run; the C literal parser for launch arguments is compared with the Python lexer on about 12,000 strings; and generated C compiles warning-free with -std=c99 -Wall -Wextra -Wpedantic -Werror. A fresh-clone check also compiled selected examples at -O0 and -O2 under those strict flags.\n\nQualification to state out loud: generated-C execution is validated on Windows with MSYS2 UCRT64 GCC. On Linux/WSL the compiler-side tests passed but generated C was not run there. I make no claim of comprehensive cross-platform validation.\n\nLikely question: 'Why not a pass percentage?' Because there is one recorded configuration and no failing runs to report against; a percentage would add nothing.");
  card(s, 0.6, 1.5, 5.4, 4.7, { line: { color: ACC, width: 1.5 } });
  T(s, "205", 0.9, 1.6, 4.8, 1.9, { fontSize: 110, bold: true, color: ACC, valign: "middle" });
  T(s, "automated tests passed", 0.9, 3.55, 4.8, 0.5, { fontSize: 22, bold: true });
  T(s, "0 skipped · recorded full run", 0.9, 4.1, 4.8, 0.4, { fontSize: 16, color: MUTED });
  T(s, "Windows 11 · Python 3.11.9 · MSYS2 UCRT64 GCC 16.1.0", 0.9, 4.6, 4.8, 0.6, { fontSize: 13, color: MUTED });
  T(s, "Current main has 257 tests: these 205 plus 52 Studio tests.", 0.9, 5.35, 4.8, 0.7, { fontSize: 13, color: TXT });
  const tiles = [
    ["Strict C99", "Generated C compiles warning-free with -Wall -Wextra -Wpedantic -Werror (-O0 and -O2 on selected examples, fresh clone)", VIOLET],
    ["Byte-for-byte", "Runtime spec cases and every command in docs/demonstration.md compared exactly: stdout, stderr, exit status", CYAN],
    ["35,000 floats", "Float formatting checked against Python’s repr on every test run", BLUE],
    ["≈12,000 strings", "C literal parser for --set compared with the Python lexer", ORANGE],
  ];
  tiles.forEach(([h, d, c], i) => {
    const x = 6.3 + (i % 2) * 3.25, y = 1.5 + Math.floor(i / 2) * 2.4;
    card(s, x, y, 3.1, 2.25);
    T(s, h, x + 0.22, y + 0.18, 2.7, 0.45, { fontSize: 20, bold: true, color: c });
    T(s, d, x + 0.22, y + 0.72, 2.7, 1.45, { fontSize: 13, color: MUTED });
  });
  T(s, "Validated environment: Windows 11, MSYS2 UCRT64 GCC 16.1. Linux/WSL: compiler-side tests passed; generated-C execution was not validated there. No cross-platform claim.", 0.6, 6.35, 12.13, 0.55, { fontSize: 12, color: MUTED });
}

// =====================================================================
// 17. Performance and evaluation
// =====================================================================
{
  const s = contentSlide("Evaluation", "Performance and evaluation",
    "These are previously recorded results from benchmarks/benchmark.py and docs/evaluation.md, measured on one Windows 11 machine (AMD, 8 logical CPUs) with Python 3.11.9 and GCC 16.1.0, median of five runs, on 2026-10-25. I did not re-run the benchmark here: a Linux re-run would be a different environment and would not be comparable.\n\nThe chart shows only front-end time, which is the CAUSA compiler up to Causal IR: lexing, parsing, semantic analysis and IR construction. It is in milliseconds and grows with program size: 1.2 ms for the 6-let pricing program up to 177 ms for 1,000 lets. The table keeps native compilation (gcc at -O0 and -O2) and run time as separate columns on purpose, because they are different quantities on different scales: gcc takes seconds, the front end takes milliseconds. Compilation dominates these timings; the generated C has one switch case per IR node, which -O2 optimizes slowly. Executables finish in roughly 24 to 29 ms, which is close to process start-up cost on this machine, so these runs cannot distinguish workloads.\n\nCaveats to state: one machine, one OS, one C compiler, one session; workloads other than pricing are synthetic; wall-clock noise of up to about 30 percent between runs was observed. This is an engineering evaluation, not a speed comparison with any other language and not a claim of superiority.\n\nLikely question: 'Does the optimizer speed things up?' Not measurably here: it cut fan-1000 from 8,002 to 5,001 IR nodes but changed neither run time nor gcc time noticeably, and it never changed program output.");
  panel(s, 0.6, 1.45, 5.6, 4.2);
  panel(s, 6.4, 1.45, 6.33, 2.95);
  s.addChart(pres.charts.BAR, [{ name: "Front end (ms)", labels: ["pricing (6 lets)", "chain-100", "chain-1000", "fan-1000"], values: [1.2, 7.4, 102, 177] }], {
    x: 0.6, y: 1.45, w: 5.6, h: 4.2, barDir: "col", chartColors: [CYAN],
    showTitle: true, title: "Front-end time by workload (ms, median of 5)", titleColor: TXT, titleFontSize: 13, titleFontFace: "+mn-lt",
    showValue: true, dataLabelColor: TXT, dataLabelFontSize: 12, dataLabelFontFace: "+mn-lt", dataLabelPosition: "outEnd", dataLabelFormatCode: "#,##0.0",
    catAxisLabelColor: MUTED, catAxisLabelFontSize: 11, catAxisLabelFontFace: "+mn-lt",
    valAxisLabelColor: MUTED, valAxisLabelFontSize: 11, valAxisLabelFontFace: "+mn-lt", valAxisMaxVal: 200, valAxisMinVal: 0,
    valGridLine: { color: LINE, size: 0.5 }, catGridLine: { style: "none" }, showLegend: false,
    showValAxisTitle: true, valAxisTitle: "milliseconds", valAxisTitleColor: MUTED, valAxisTitleFontSize: 11, valAxisTitleFontFace: "+mn-lt", barGapWidthPct: 60,
  });
  // table: three separated quantities
  const hdr = (t, c) => ({ text: t, options: { bold: true, color: c, fill: { color: SURF2 }, fontSize: 12, align: "right", fontFace: SANS } });
  const cell = (t, o = {}) => ({ text: t, options: Object.assign({ color: TXT, fontSize: 13, align: "right", fontFace: MONO, fill: { color: PANEL } }, o) });
  const rows = [
    [{ text: "workload", options: { bold: true, color: MUTED, fill: { color: SURF2 }, fontSize: 12, fontFace: SANS } }, hdr("front end", CYAN), hdr("gcc -O0", VIOLET), hdr("gcc -O2", VIOLET), hdr("run", TEAL)],
    [cell("pricing", { align: "left" }), cell("1.2"), cell("366"), cell("451"), cell("23.9")],
    [cell("chain-100", { align: "left" }), cell("7.4"), cell("438"), cell("846"), cell("24.8")],
    [cell("chain-1000", { align: "left" }), cell("102"), cell("1,651"), cell("5,769"), cell("27.8")],
    [cell("fan-1000", { align: "left" }), cell("177"), cell("2,667"), cell("10,561"), cell("28.8")],
  ];
  s.addTable(rows, { x: 6.5, y: 1.55, w: 6.13, colW: [1.53, 1.15, 1.15, 1.15, 1.15], rowH: 0.55, border: { type: "solid", color: LINE, pt: 0.75 }, margin: [0, 0.12, 0, 0.12], valign: "middle", objectName: "benchmark-table" });
  T(s, "milliseconds, median of 5 runs. Three different quantities: CAUSA front end, native C compile, program run.", 6.4, 4.5, 6.33, 0.45, { fontSize: 12, color: GREY });
  const notes = [["Compilation dominates", "gcc at -O2 took 5.8–10.6 s for 1,000 lets; the CAUSA front end took 0.1–0.2 s.", VIOLET], ["Runs ≈ process start-up", "Executables finish in about 24–29 ms in every workload.", TEAL]];
  notes.forEach(([h, d, c], i) => {
    const x = 6.5 + i * 3.17;
    card(s, x, 5.0, 3.06, 1.2);
    T(s, h, x + 0.18, 5.08, 2.75, 0.35, { fontSize: 14, bold: true, color: c });
    T(s, d, x + 0.18, 5.45, 2.75, 0.75, { fontSize: 12, color: GREY });
  });
  T(s, "Recorded on one Windows 11 machine (8 logical CPUs, Python 3.11.9, GCC 16.1.0); environment-dependent engineering measurements, not a speed claim.", 0.6, 6.4, 12.13, 0.5, { fontSize: 12, color: GREY });
}

// =====================================================================
// 18. Limitations and future work
// =====================================================================
pres.addSection({ title: "Closing" });
{
  const s = contentSlide("Closing", "Limitations and future work",
    "Honest scope. Completed: everything in language version 1 and the Studio application, listed in the left column. Limitations are things that are true today. First, portability: generated-C execution is validated on Windows with MSYS2 UCRT64 GCC; Linux, macOS, Clang and MSVC are untested, and float formatting depends on a correctly rounded printf and strtod in the C library. Second, scope: no conditionals, loops, functions, recursion, mutation, strings or collections; conditionals are deferred because static and dynamic dependency semantics give different explain and impact answers. Third, performance: the front end grows faster than linearly on very long dependency chains because each binding stores its full transitive dependency set, and the C compiler dominates build time. Studio runs one file at a time and cannot set launch values.\n\nFuture work is proposed, not implemented: a single build and run command that invokes the C compiler, testing other compilers and C libraries, the deferred language features, Studio usability improvements, and a more systematic performance evaluation on larger and more realistic programs.\n\nLikely question: 'What would you do first?' Cross-platform validation and a one-command build, because they remove the most friction for new users.");
  const cols = [
    ["Completed", TEAL, ["Language v1: inputs, lets, show, explain, whatif, impact, assert", "Causal IR with verified, dependency-preserving optimizer", "C99 backend and C runtime", "Launch-time --set inputs", "CAUSA Studio desktop app"]],
    ["Limitations today", ORANGE, ["Generated C validated on Windows + MSYS2 UCRT64 GCC only", "No conditionals, loops, functions, strings, collections", "Front end grows faster than linear on long chains", "C compiler dominates build time", "Studio: one file at a time, no launch values"]],
    ["Not built yet", VIOLET, ["Test Linux, macOS, Clang, MSVC", "One command to build and run", "Deferred language features", "Studio usability and visualization", "Broader performance evaluation"]],
  ];
  cols.forEach(([h, c, items], i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.45, 3.93, 5.1);
    T(s, h, x + 0.25, 1.62, 3.5, 0.45, { fontSize: 19, bold: true, color: c });
    T(s, items.map((t, k) => ({ text: t, options: { bullet: true, breakLine: k < items.length - 1 } })), x + 0.25, 2.25, 3.45, 4.1, { fontSize: 16, paraSpaceAfter: 10 });
  });
}

// =====================================================================
// 18b. Sample source code (verbatim excerpt of causa/optimizer.py)
// =====================================================================
{
  const s = contentSlide("Closing", "Sample code: the optimizer's safety check",
    "An excerpt from causa/optimizer.py (code verbatim, comments shortened), the end of optimize(). After rewriting, the optimizer removes only constants that lost all users, re-validates the module (which re-derives the binding-level graph and compares it with the recorded provenance), and then checks that bindings, provenance, anchors and actions are untouched. A violation raises an internal compiler error rather than silently producing different output. This is the code behind the invariant on the Causal IR slide.");
  const L = [
    ["    # Remove consts that lost all users.", MUTED],
    ["    used = {o for n in nodes.values() for o in n.operands}", TXT],
    ["    used |= {s.root for s in steps if isinstance(s, Assert)}", TXT],
    ["    for node_id in sorted(nodes):", VIOLET],
    ["        if nodes[node_id].kind is NodeKind.CONST and node_id not in used:", TXT],
    ["            del nodes[node_id]", TXT],
    ["            log.append(Rewrite(\"remove\", node_id, \"const node\", \"no remaining users\"))", ORANGE],
    ["", TXT],
    ["    result = replace(module, nodes=tuple(nodes.values()), steps=tuple(steps))", TXT],
    ["    validate_ir(result)  # re-derives the binding-level graph, compares with provenance", GREEN],
    ["    _check_preserved(module, result)", GREEN],
    ["    return OptimizationResult(result, tuple(log))", TXT],
  ];
  codeCard(s, 0.6, 1.35, 8.1, 4.5, "causa/optimizer.py  (excerpt of optimize; comments shortened)", consoleRuns(L, 10.5));
  card(s, 9.0, 1.35, 3.73, 1.35);
  T(s, "Only constants are removed", 9.2, 1.5, 3.4, 0.3, { fontSize: 14, bold: true, color: CYAN });
  T(s, "A constant cannot raise a runtime error, so deleting unused ones is safe.", 9.2, 1.9, 3.4, 0.7, { fontSize: 12, color: MUTED });
  card(s, 9.0, 2.9, 3.73, 1.35);
  T(s, "Re-derive and compare", 9.2, 3.05, 3.4, 0.3, { fontSize: 14, bold: true, color: GREEN });
  T(s, "validate_ir rebuilds the dependency graph and checks it against provenance.", 9.2, 3.45, 3.4, 0.75, { fontSize: 12, color: MUTED });
  card(s, 9.0, 4.45, 3.73, 1.4);
  T(s, "Fail loudly", 9.2, 4.6, 3.4, 0.3, { fontSize: 14, bold: true, color: ORANGE });
  T(s, "Any change to a binding, anchor or action raises an internal compiler error.", 9.2, 5.0, 3.4, 0.75, { fontSize: 12, color: MUTED });
  T(s, "Full source: github.com/ujvall/causa", 0.6, 6.15, 8, 0.4, { fontSize: 14, color: MUTED });
}

// =====================================================================
// 19. Conclusion
// =====================================================================
{
  DARKS = [];
  const s = pres.addSlide({ masterName: "CAUSA_TITLE", sectionTitle: "Closing" });
  s.addNotes(
    "Close. CAUSA connects compilation with explainability and counterfactual reasoning: a small language and compiler in which dependencies are first-class, so a program can say why a value was produced, what depends on a binding, and what would happen under different inputs, all without disturbing the original execution. Three takeaways on the slide. The implementation is verified by an automated test suite and demonstrated by CAUSA Studio. The limitations are real and listed. Thank you; I am happy to take questions.\n\nSuggested backup answers: dependency direction (binding to names it uses, reverse derived); why C (native output, small testable runtime); why constant folding is safe (never folds anything that could raise a runtime error, and the dependency graph is re-verified); what is not claimed (no cross-platform validation, no performance superiority, no claim of being the first system of its kind)."
  );
  T(s, "CAUSA connects compilation with explainability and counterfactual reasoning.", 0.8, 0.9, 11.5, 1.6, { fontSize: 38, bold: true, valign: "top" });
  const tk = [["Understand", "why a value was produced", "explain"], ["Trace", "the impact of a binding", "impact"], ["Explore", "alternative inputs without changing the original execution", "whatif"]];
  tk.forEach(([h, d, op], i) => {
    const x = 0.8 + i * 4.0;
    card(s, x, 2.9, 3.8, 2.3);
    T(s, op, x + 0.25, 3.05, 3.3, 0.4, { fontFace: MONO, fontSize: 16, bold: true, color: GREY });
    T(s, h, x + 0.25, 3.5, 3.3, 0.5, { fontSize: 24, bold: true, color: ACC, fontFace: SERIF });
    T(s, d, x + 0.25, 4.05, 3.3, 1.0, { fontSize: 16 });
  });
  T(s, "Questions?", 0.8, 5.3, 6, 0.9, { fontSize: 48, bold: true, valign: "middle" });
  T(s, [{ text: "github.com/ujvall/causa", options: { hyperlink: { url: "https://github.com/ujvall/causa", tooltip: "CAUSA source code" }, color: CYAN, underline: { style: "sng", color: CYAN } } }], 0.8, 6.3, 7, 0.45, { fontSize: 20, bold: true, valign: "middle" });
  // echo motif
  panel(s, 8.3, 5.45, 4.43, 1.55);
  const nodes = [["price", 8.5, 6.0, GREEN], ["savings", 10.0, 5.75, BLUE], ["total", 11.4, 6.0, CYAN]];
  arrow(s, 8.5 + 1.2, 6.3, 10.0, 6.05, MUTED, 1.5);
  arrow(s, 10.0 + 1.2, 6.05, 11.4, 6.3, MUTED, 1.5);
  nodes.forEach(([l, x, y, c]) => node(s, x, y, 1.2, 0.6, l, c, null, SURF2, 14));
}

// =====================================================================
// 20. References (appendix)
// =====================================================================
{
  const s = contentSlide("Closing", "Appendix: references",
    "Verification: each entry's title, authors, year and venue were checked against a publisher, library or official project page while building this deck. DOIs are given only where a page showed one. Items [1] and [5] show venue, volume and pages but no DOI, because none was confirmed. [7] has a stable official page but no DOI listed there. [8] is the CGO 2021 paper listed on Google Research's publication page; no DOI was confirmed. [10] is an arXiv preprint (not peer reviewed). A Halpern and Pearl structural-model causality paper was considered for the counterfactual theme and dropped because its journal venue could not be verified. Recent sources (2022 to 2024) are [6] (2022) and [10] (2023).");
  const refs = [
    "[1] M. Weiser, “Program Slicing,” IEEE Transactions on Software Engineering, vol. 10, no. 4, pp. 352–357, 1984.",
    "[2] J. Ferrante, K. J. Ottenstein, J. D. Warren, “The Program Dependence Graph and Its Use in Optimization,” ACM TOPLAS, vol. 9, no. 3, pp. 319–349, 1987. doi:10.1145/24039.24041",
    "[3] J. Cheney, L. Chiticariu, W.-C. Tan, “Provenance in Databases: Why, How, and Where,” Foundations and Trends in Databases, vol. 1, no. 4, pp. 379–474, 2009. doi:10.1561/1900000006",
    "[4] J. Cheney, A. Ahmed, U. A. Acar, “Provenance as dependency analysis,” Mathematical Structures in Computer Science, vol. 21, no. 6, pp. 1301–1337, 2011. doi:10.1017/S0960129511000211",
    "[5] A. J. Ko, B. A. Myers, “Designing the Whyline: A Debugging Interface for Asking Questions About Program Behavior,” CHI 2004, Vienna, pp. 151–158.",
    "[6] A.-H. Karimi, G. Barthe, B. Schölkopf, I. Valera, “A Survey of Algorithmic Recourse: Contrastive Explanations and Consequential Recommendations,” ACM Computing Surveys, vol. 55, no. 5, 2022. doi:10.1145/3527848",
    "[7] C. Lattner, V. Adve, “LLVM: A Compilation Framework for Lifelong Program Analysis & Transformation,” CGO 2004, Palo Alto. https://llvm.org/pubs/2004-01-30-CGO-LLVM.html",
    "[8] C. Lattner, M. Amini, U. Bondhugula, A. Cohen, A. Davis, J. Pienaar, R. Riddle, T. Shpeisman, N. Vasilache, O. Zinenko, “MLIR: Scaling Compiler Infrastructure for Domain Specific Computation,” CGO 2021. https://research.google/pubs/mlir-scaling-compiler-infrastructure-for-domain-specific-computation/",
    "[9] J. Chen, J. Patra, M. Pradel, Y. Xiong, H. Zhang, D. Hao, L. Zhang, “A Survey of Compiler Testing,” ACM Computing Surveys, vol. 53, no. 1, pp. 1–36, 2020. doi:10.1145/3363562",
    "[10] H. Ma, “A Survey of Modern Compiler Fuzzing,” arXiv preprint, 2023 (not peer reviewed). doi:10.48550/arXiv.2306.06884",
  ];
  const left = refs.slice(0, 5), right = refs.slice(5);
  const mk = (arr) => arr.map((t, i) => ({ text: t, options: { breakLine: i < arr.length - 1, fontSize: 13, color: TXT, paraSpaceAfter: 9 } }));
  card(s, 0.6, 1.4, 5.95, 5.35);
  T(s, mk(left), 0.8, 1.55, 5.6, 5.1, {});
  card(s, 6.78, 1.4, 5.95, 5.35);
  T(s, mk(right), 6.98, 1.55, 5.6, 5.1, {});
}

// ---------- write ----------
(async () => {
  await pres.writeFile({ fileName: OUT });
  const apply = process.env.PPTX_APPLY_THEME;
  if (apply && fs.existsSync(apply)) {
    const { applyTheme } = require(apply);
    await applyTheme(OUT, THEME);
    console.log("theme applied");
  }
  console.log("wrote", OUT);
})();
