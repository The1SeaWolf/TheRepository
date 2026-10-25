"use strict";
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props);
  n.append(...kids.filter(k => k != null));
  return n;
};
const fmt = n => (Math.round(n * 10) / 10).toString();
const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
const shiftDay = (day, by) => { const d = new Date(day + "T12:00:00"); d.setDate(d.getDate() + by); return d.toLocaleDateString("sv"); };

async function api(path, opts) {
  const r = await fetch("/api" + path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(msg);
  }
  return r.json();
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function status(msg, err = false) { const s = $("#status"); s.textContent = msg; s.className = err ? "err" : ""; }

// ---- navigation -----------------------------------------------------------
let day = today();
document.querySelectorAll("nav button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(name) {
  document.querySelectorAll("main > section").forEach(s => s.hidden = s.id !== "tab-" + name);
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  stopScan();
  if (name === "today") loadDay();
  if (name === "add") loadRecent();
  if (name === "history") loadHistory();
}
$("#day").onchange = e => { day = e.target.value || today(); loadDay(); };
$("#prev").onclick = () => { day = shiftDay(day, -1); loadDay(); };
$("#next").onclick = () => { day = shiftDay(day, 1); loadDay(); };

// ---- today ----------------------------------------------------------------
async function loadDay() {
  $("#day").value = day;
  const d = await api("/day/" + day);
  for (const k of ["carbs", "fat"]) {
    const total = d.totals[k + "_g"], goal = d.goals[k + "_g"];
    $("#t-" + k).textContent = fmt(total);
    $("#g-" + k).textContent = goal ? `of ${fmt(goal)} g` : "no goal set";
    const bar = $("#b-" + k);
    bar.style.width = goal ? Math.min(100, total / goal * 100) + "%" : "0";
    bar.classList.toggle("over", !!goal && total > goal);
  }
  const box = $("#entries");
  box.replaceChildren();
  if (!d.entries.length) box.append(el("div", { className: "empty", textContent: "Nothing logged yet." }));
  for (const meal of ["breakfast", "lunch", "dinner", "snack"]) {
    const items = d.entries.filter(e => e.meal === meal);
    if (!items.length) continue;
    box.append(el("div", { className: "meal" }, el("h3", { textContent: meal }), ...items.map(e =>
      el("div", { className: "item" },
        el("div", { className: "n" }, el("b", { textContent: e.name }), el("small", { textContent: [e.amount, e.source !== "manual" ? e.source : ""].filter(Boolean).join(" · ") })),
        el("div", {}, el("b", { textContent: fmt(e.carbs_g) + " c" }), " ", el("small", { textContent: fmt(e.fat_g) + " f" })),
        el("button", { className: "x", textContent: "✕", ariaLabel: "Delete", onclick: async () => {
          if (confirm(`Delete "${e.name}"?`)) { await api("/entries/" + e.id, { method: "DELETE" }); loadDay(); }
        } })))));
  }
}

// ---- add: drafts ----------------------------------------------------------
const defaultMeal = () => { const h = new Date().getHours(); return h < 10 ? "breakfast" : h < 15 ? "lunch" : h < 21 ? "dinner" : "snack"; };

/** units: [{label, carbs, fat}] = nutrition per ONE of that unit. */
function addDraft({ name, source, units, unit = 0, amount = 1 }) {
  const card = el("div", { className: "draft" });
  const nameIn = el("input", { value: name });
  const amtIn = el("input", { type: "number", min: "0", step: "any", value: amount, inputMode: "decimal" });
  const unitSel = el("select", {}, ...units.map((u, i) => el("option", { value: i, textContent: u.label })));
  unitSel.value = unit;
  const carbsIn = el("input", { type: "number", min: "0", step: "0.1", inputMode: "decimal" });
  const fatIn = el("input", { type: "number", min: "0", step: "0.1", inputMode: "decimal" });
  const mealSel = el("select", {}, ...["breakfast", "lunch", "dinner", "snack"].map(m => el("option", { value: m, textContent: m })));
  mealSel.value = defaultMeal();
  const recalc = () => {
    const u = units[unitSel.value], a = parseFloat(amtIn.value) || 0;
    carbsIn.value = fmt(u.carbs * a); fatIn.value = fmt(u.fat * a);
  };
  amtIn.oninput = unitSel.onchange = recalc;
  recalc();
  const add = el("button", { className: "primary", textContent: "Add to " + day, onclick: async () => {
    if (!nameIn.value.trim()) return nameIn.focus();
    add.disabled = true;
    try {
      const u = units[unitSel.value];
      await post("/entries", { day, meal: mealSel.value, name: nameIn.value.trim(), source,
        amount: u.single ? "" : `${amtIn.value} ${u.label}`, carbs_g: +carbsIn.value || 0, fat_g: +fatIn.value || 0 });
      card.remove(); status("Added ✓");
    } catch (e) { status(e.message, true); add.disabled = false; }
  } });
  card.append(
    nameIn,
    ...(units[0].single ? [] : [el("div", { className: "row" }, el("label", {}, "Amount", amtIn), el("label", {}, "Unit", unitSel))]),
    el("div", { className: "row" }, el("label", {}, "Carbs (g)", carbsIn), el("label", {}, "Fat (g)", fatIn)),
    el("div", { className: "foot" }, mealSel, add, el("button", { textContent: "✕", ariaLabel: "Dismiss", onclick: () => card.remove() })));
  $("#drafts").prepend(card);
}

function draftFromFood(f) {
  const units = [];
  if (f.carbs_serving != null) units.push({ label: f.serving_desc ? `serving (${f.serving_desc})` : "serving", carbs: f.carbs_serving, fat: f.fat_serving });
  units.push({ label: "g", carbs: f.carbs_100g / 100, fat: f.fat_100g / 100 });
  addDraft({ name: [f.brand, f.name].filter(Boolean).join(" – "), source: f.source, units, amount: units.length > 1 ? 1 : 100 });
}

// ---- add: photos ----------------------------------------------------------
async function shrink(file, max = 1600) {
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const c = el("canvas", { width: Math.round(bmp.width * scale), height: Math.round(bmp.height * scale) });
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    return await new Promise(r => c.toBlob(r, "image/jpeg", 0.85));
  } catch { return file; }
}

document.querySelectorAll("input[data-photo]").forEach(inp => inp.onchange = async () => {
  const file = inp.files[0]; inp.value = "";
  if (!file) return;
  const kind = inp.dataset.photo;
  status(kind === "label" ? "Reading label…" : "Analysing meal…");
  const fd = new FormData();
  fd.append("image", await shrink(file), "photo.jpg");
  fd.append("hint", $("#hint").value);
  try {
    const r = await api("/analyze/" + kind, { method: "POST", body: fd });
    if (kind === "label") {
      if (!r.is_label) throw new Error("That doesn't look like a nutrition label. " + r.notes);
      addDraft({ name: r.name || "Packaged food", source: "label",
        units: [{ label: r.serving_desc ? `serving (${r.serving_desc})` : "serving", carbs: r.carbs_g, fat: r.fat_g }] });
      status(r.notes || "Check the numbers against the label, then add.");
    } else {
      if (!r.items.length) throw new Error("No food found in that photo.");
      r.items.forEach(i => addDraft({ name: i.name, source: "photo",
        units: [{ label: i.portion_desc || "portion", carbs: i.carbs_g, fat: i.fat_g, single: true }] }));
      status("Estimates only (" + r.items.map(i => i.confidence).join("/") + " confidence). " + (r.notes || ""));
    }
  } catch (e) { status(e.message, true); }
});

// ---- add: search, barcode, manual, recent ---------------------------------
$("#search-form").onsubmit = async e => {
  e.preventDefault();
  const q = $("#q").value.trim(); if (q.length < 2) return;
  status("Searching…");
  try {
    const r = await api("/search?q=" + encodeURIComponent(q));
    status(r.results.length ? "" : "No results" + (r.errors.length ? " (" + r.errors.join("; ") + ")" : ""), !r.results.length);
    $("#drafts").replaceChildren();
    // Results are listed as tappable rows; tapping opens an editable draft.
    const list = el("div", { className: "draft" }, ...r.results.map(f =>
      el("button", { textContent: `${f.brand ? f.brand + " – " : ""}${f.name}  ·  ${fmt(f.carbs_100g)}c / ${fmt(f.fat_100g)}f per 100g`,
        onclick: () => { list.remove(); draftFromFood(f); } })));
    $("#drafts").append(list);
  } catch (err) { status(err.message, true); }
};

async function lookupBarcode(code) {
  status("Looking up " + code + "…");
  try { draftFromFood(await api("/barcode/" + code)); status(""); }
  catch (e) { status(e.message + " — try photographing the nutrition label instead.", true); }
}

let stream = null, scanning = false;
function stopScan() { scanning = false; stream?.getTracks().forEach(t => t.stop()); stream = null; $("#video").hidden = true; }
$("#scan").onclick = async () => {
  if (scanning) return stopScan();
  if (!("BarcodeDetector" in window) || !navigator.mediaDevices?.getUserMedia) {
    const code = prompt("Live scanning isn't supported in this browser. Type the barcode number:");
    return code && lookupBarcode(code.replace(/\D/g, ""));
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
  } catch (e) { return status("Camera unavailable: " + e.message, true); }
  const video = $("#video"); video.srcObject = stream; video.hidden = false; await video.play();
  scanning = true; status("Point the camera at the barcode…");
  const detector = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
  while (scanning) {
    const [hit] = await detector.detect(video).catch(() => []);
    if (hit) { stopScan(); return lookupBarcode(hit.rawValue); }
    await new Promise(r => setTimeout(r, 300));
  }
};

$("#manual").onclick = () => addDraft({ name: "", source: "manual", units: [{ label: "entry", carbs: 0, fat: 0, single: true }] });

async function loadRecent() {
  const r = await api("/recent");
  $("#recent-h").hidden = !r.length;
  $("#recent").replaceChildren(...r.map(f => el("div", { className: "item" },
    el("div", { className: "n" }, el("b", { textContent: f.name }), el("small", { textContent: f.amount })),
    el("small", { textContent: `${fmt(f.carbs_g)}c ${fmt(f.fat_g)}f` }),
    el("button", { textContent: "+", onclick: () => addDraft({ name: f.name, source: "recent",
      units: [{ label: f.amount || "portion", carbs: f.carbs_g, fat: f.fat_g, single: true }] }) }))));
}

// ---- history & goals ------------------------------------------------------
async function loadHistory() {
  const h = await api("/history?days=30&end=" + today());
  const goals = await api("/goals");
  $("#goals").carbs_g.value = goals.carbs_g ?? ""; $("#goals").fat_g.value = goals.fat_g ?? "";
  const W = 600, H = 220, pad = 28, n = h.days.length;
  const max = Math.max(10, ...h.days.map(d => Math.max(d.carbs_g, d.fat_g)), h.goals.carbs_g || 0, h.goals.fat_g || 0) * 1.1;
  const x = i => pad + (i + 0.5) * (W - pad) / n, y = v => H - pad - v / max * (H - pad * 2);
  const NS = "http://www.w3.org/2000/svg";
  const s = (t, a) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Carbs and fat per day, last 30 days" });
  const line = (key, color) => {
    svg.append(s("polyline", { fill: "none", stroke: color, "stroke-width": 2, points: h.days.map((d, i) => `${x(i)},${y(d[key])}`).join(" ") }));
    const g = h.goals[key]; if (g) svg.append(s("line", { x1: pad, x2: W, y1: y(g), y2: y(g), stroke: color, "stroke-dasharray": "4 4", opacity: .5 }));
  };
  line("fat_g", "#d98a1c"); line("carbs_g", "#1f7a4d");
  [[h.days[0].day, pad], [h.days[n - 1].day, W - 40]].forEach(([t, px]) => { const e = s("text", { x: px, y: H - 8, fill: "currentColor", "font-size": 11 }); e.textContent = t.slice(5); svg.append(e); });
  const leg = s("text", { x: pad, y: 16, "font-size": 12, fill: "#1f7a4d" }); leg.textContent = "● carbs g"; svg.append(leg);
  const leg2 = s("text", { x: pad + 80, y: 16, "font-size": 12, fill: "#d98a1c" }); leg2.textContent = "● fat g"; svg.append(leg2);
  $("#chart").replaceChildren(svg);
}
$("#goals").onsubmit = async e => {
  e.preventDefault();
  const f = e.target, v = k => f[k].value === "" ? null : +f[k].value;
  await api("/goals", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ carbs_g: v("carbs_g"), fat_g: v("fat_g") }) });
  loadHistory();
};

loadDay().catch(e => status(e.message, true));
