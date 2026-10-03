const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (n) => Number(n).toLocaleString("en-US");

const RESULT = {
  applies: { label: "Applies", why: "In force and covers this building." },
  unknown: { label: "Unknown", why: "Coverage turns on a fact the public record does not show. Supply it in the facts panel." },
  superseded: { label: "Superseded", why: "Covered, but a local rule on the same subject governs." },
  not_yet_effective: { label: "Not yet in force", why: "Enacted, with an effective date after the query date." },
  pending: { label: "Bill, not law", why: "Proposed. Shown so you can see what may be coming." },
  not_covered: { label: "Outside coverage", why: "Checked against this building's facts and excluded. Not part of the scored answer." },
};
const CATEGORY = {
  rent_increase_limits: "Rent increases",
  just_cause_eviction: "Just-cause eviction",
  security_deposits: "Security deposits",
  application_screening_fees: "Screening fees",
  screening_restrictions: "Screening rules",
  algorithmic_rent_setting: "Algorithmic pricing",
};
const STATE_NAME = { CA: "California", NJ: "New Jersey", MA: "Massachusetts" };

let current = null;

/* Landing */
fetch("/api/insights").then((r) => r.json()).then((data) => {
  $("stats").innerHTML = [
    [fmt(data.rules), `rules, each quoted from ${data.documents} public documents`],
    [fmt(data.addresses), `addresses in ${data.cities} cities, checked rule by rule`],
    [fmt(data.naive_wrong_city), "addresses whose mailing city is not their legal city"],
    [fmt(data.naive_overreach), "rule matches a city-name lookup would wrongly apply"],
    [fmt(data.conflicts), "open questions in the law flagged for review"],
  ].map(([n, l]) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");

  const census = data.place_methods.census || 0;
  $("proof-city").textContent = `${data.naive_wrong_city} of ${data.addresses} sample addresses use a neighborhood or mailing name. ${census} legal cities are confirmed by the US Census Geocoder.`;
  $("proof-coverage").textContent = `${fmt(data.naive_overreach)} rule-and-building pairs fall outside a rule's own cutoff. A city-name lookup would report them as applying.`;
  $("proof-status").textContent = `${data.pending_or_future} rules are bills or not yet in force on 1 Oct 2026. They are shown, and never counted as law.`;

  const top = Math.max(...data.unknown_drivers.map((d) => d.answers), 1);
  $("drivers").innerHTML = data.unknown_drivers.map((d) => `
    <div class="driver">
      <div>${esc(d.label[0].toUpperCase() + d.label.slice(1))}</div>
      <div class="bar"><span style="width:${(100 * d.answers / top).toFixed(1)}%"></span></div>
      <div class="num">${fmt(d.answers)} answers · ${fmt(d.addresses)} addresses</div>
    </div>`).join("");
});

/* Search */
let timer;
let options = [];
let cursor = -1;
$("q").addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(search, 120);
});
$("q").addEventListener("keydown", (event) => {
  if (!options.length) return;
  if (event.key === "ArrowDown") cursor = Math.min(cursor + 1, options.length - 1);
  else if (event.key === "ArrowUp") cursor = Math.max(cursor - 1, 0);
  else if (event.key === "Enter") { open(options[Math.max(cursor, 0)].address_id); return; }
  else return;
  event.preventDefault();
  [...$("matches").children].forEach((li, i) => li.classList.toggle("active", i === cursor));
});

async function search() {
  const text = $("q").value.trim();
  $("matches").innerHTML = "";
  options = [];
  cursor = -1;
  if (text.length < 2) return;
  options = await fetch("/api/addresses?q=" + encodeURIComponent(text)).then((r) => r.json());
  $("matches").innerHTML = options.map((o) => `<li data-id="${esc(o.address_id)}">${esc(o.label)}</li>`).join("");
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-id]");
  if (target) { event.preventDefault(); open(target.dataset.id); }
  else if (!event.target.closest(".search")) $("matches").innerHTML = "";
});

/* Report */
function params() {
  const p = new URLSearchParams(location.search);
  return { id: p.get("a"), as_of: p.get("as_of") || "", year_built: p.get("year_built") || "", units: p.get("units") || "", owner_occupied: p.get("owner_occupied") || "", public_funding: p.get("public_funding") || "" };
}

function open(id, extra = {}) {
  const query = new URLSearchParams({ a: id });
  for (const [k, v] of Object.entries(extra)) if (v) query.set(k, v);
  history.pushState({}, "", "/?" + query.toString());
  render();
}

window.addEventListener("popstate", render);

async function render() {
  const p = params();
  $("matches").innerHTML = "";
  if (!p.id) {
    document.body.classList.remove("reporting");
    $("report").classList.add("hidden");
    $("landing").classList.remove("hidden");
    $("q").value = "";
    return;
  }
  const query = new URLSearchParams({ address_id: p.id });
  for (const k of ["as_of", "year_built", "units", "owner_occupied", "public_funding"]) if (p[k]) query.set(k, p[k]);
  const response = await fetch("/api/lookup?" + query.toString());
  if (!response.ok) { $("report-body").innerHTML = `<p>Address not found.</p>`; return; }
  current = await response.json();
  document.body.classList.add("reporting");
  $("landing").classList.add("hidden");
  $("report").classList.remove("hidden");
  $("report-body").innerHTML = report(current);
  $("q").value = `${current.street_address}, ${current.postal_city}, ${current.state}`;
  window.scrollTo({ top: 0 });
  bindFacts();
}

function placeBadge(place) {
  if (place.method === "census") return `<span class="badge census" title="${esc(place.note)}">Legal city confirmed by US Census Geocoder</span>`;
  if (place.method === "alias") return `<span class="badge alias" title="${esc(place.note)}">${esc(place.note)}</span>`;
  if (place.method === "disagreement") return `<span class="badge review">${esc(place.note)}</span>`;
  return `<span class="badge" title="${esc(place.note)}">City from the address record</span>`;
}

function report(d) {
  const supplied = new Set(d.supplied);
  const counts = Object.entries(d.counts).filter(([, n]) => n).map(([k, n]) =>
    `<span class="count" style="border-left-color:var(--${cssVar(k)})">${n} ${RESULT[k].label.toLowerCase()}</span>`).join("");
  const groups = ["applies", "unknown", "superseded", "not_yet_effective", "pending"].map((result) => {
    const hits = d.hits.filter((h) => h.result === result);
    if (!hits.length) return "";
    const byTopic = Object.keys(CATEGORY).map((cat) => {
      const inTopic = hits.filter((h) => h.category === cat);
      return inTopic.length ? `<h4 class="topic">${CATEGORY[cat]} <small>${inTopic.length}</small></h4>${inTopic.map(card).join("")}` : "";
    }).join("");
    return `<div class="group" id="g-${result}"><h2>${RESULT[result].label} <small>${hits.length}</small></h2><p class="why">${RESULT[result].why}</p>${byTopic}</div>`;
  }).join("");
  const outside = d.hits.filter((h) => h.result === "not_covered");
  const outsideBlock = outside.length ? `<details class="outside"><summary>Outside coverage <small>${outside.length} checked and excluded</small></summary><p class="why">${RESULT.not_covered.why}</p>${outside.map(card).join("")}</details>` : "";
  const gaps = d.gaps.length ? `<div class="gap-box"><h3>Sources we could not read</h3><p>These cover this place, but the corpus has only a link, not the text. Their rules are not shown above; check them directly.</p><ul>${d.gaps.map((g) => `<li><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.doc_id)}</a> · ${esc(new URL(g.url).hostname)}</li>`).join("")}</ul></div>` : "";
  const settle = d.unknown_drivers.length ? `<div class="settle"><h2>What would settle the unknowns</h2><ul>${d.unknown_drivers.map((u) => `<li>${esc(u.label)}: ${u.rules} rule${u.rules > 1 ? "s" : ""}</li>`).join("")}</ul></div>` : "";
  const facts = d.facts;
  const tri = (name, value) => `<select id="f-${name}" class="${supplied.has(name) ? "supplied" : ""}">
      <option value="" ${value === null ? "selected" : ""}>Not known</option>
      <option value="yes" ${value === true ? "selected" : ""}>Yes</option>
      <option value="no" ${value === false ? "selected" : ""}>No</option></select>`;
  const from = (name, value) => supplied.has(name) ? "You supplied this" : value === null ? "Not in the public record" : `From ${esc(d.source_dataset)}`;
  return `
    <a class="back" href="/">← All addresses</a>
    <div class="report-head">
      <h1>${esc(d.street_address)}, ${esc(d.postal_city)}, ${esc(d.state)}</h1>
      <div class="where">
        <span>Legal city <b>${esc(d.legal_city)}, ${esc(d.state)}</b></span>${placeBadge(d.place)}
        <span>As of <b>${esc(d.as_of)}</b></span>
        <span>${esc(d.use_description || "")}</span>
      </div>
      <p class="legal">Not legal advice. Each rule below is quoted from a public source in the challenge corpus. Unknown means the public record lacks a fact the rule depends on.</p>
    </div>
    <div class="counts">${counts}</div>
    <div class="layout">
      <aside class="facts">
        <h2>Building facts</h2>
        <p class="hint">Change a fact or the date and every rule is checked again.</p>
        <div class="field"><label for="f-year_built">Year built</label><input id="f-year_built" inputmode="numeric" value="${facts.year_built ?? ""}" placeholder="Unknown" class="${supplied.has("year_built") ? "supplied" : ""}"><div class="from">${from("year_built", facts.year_built)}</div></div>
        <div class="field"><label for="f-units">Units in the building</label><input id="f-units" inputmode="numeric" value="${facts.units ?? ""}" placeholder="Unknown" class="${supplied.has("units") ? "supplied" : ""}"><div class="from">${from("units", facts.units)}</div></div>
        <div class="field"><label for="f-owner_occupied">Owner lives in the building</label>${tri("owner_occupied", facts.owner_occupied)}<div class="from">${from("owner_occupied", facts.owner_occupied)}</div></div>
        <div class="field"><label for="f-public_funding">Public funding or income limits</label>${tri("public_funding", facts.public_funding)}<div class="from">${from("public_funding", facts.public_funding)}</div></div>
        <div class="field"><label for="f-as_of">Query date</label><input id="f-as_of" type="date" value="${esc(d.as_of)}"></div>
        <button class="primary" id="recheck">Check again</button>
        <button class="reset" id="reset">Reset to the public record</button>
        ${settle}
      </aside>
      <div>${summary(d)}${groups}${outsideBlock}${gaps}</div>
    </div>`;
}

function summary(d) {
  const rows = Object.entries(CATEGORY).map(([cat, label]) => {
    const hits = d.hits.filter((h) => h.category === cat);
    if (!hits.length) return "";
    const binding = hits.filter((h) => h.result === "applies");
    const lead = binding.find((h) => h.level === "city" && h.key_value) || binding.find((h) => h.key_value) || binding[0];
    const notes = [];
    const n = (result) => hits.filter((h) => h.result === result).length;
    if (n("unknown")) notes.push(`${n("unknown")} unknown`);
    if (n("superseded")) notes.push(`${n("superseded")} superseded by local law`);
    if (n("not_yet_effective")) notes.push(`${n("not_yet_effective")} not yet in force`);
    if (n("pending")) notes.push(`${n("pending")} bill${n("pending") > 1 ? "s" : ""} pending`);
    if (n("not_covered")) notes.push(`${n("not_covered")} outside coverage`);
    if (hits.some((h) => h.conflict_flag)) notes.push("conflict flagged");
    const answer = lead
      ? `<b>${esc(lead.title)}</b>${lead.key_value ? ` · ${esc(lead.key_value)}` : ""}${binding.length > 1 ? ` <span class="muted">+${binding.length - 1} more in force</span>` : ""}`
      : `<span class="muted">Nothing in force decided for this building</span>`;
    return `<tr><td>${label}</td><td>${answer}</td><td class="muted">${notes.join(" · ")}</td></tr>`;
  }).join("");
  return `<div class="summary"><h2>At a glance</h2><table>${rows}</table></div>`;
}

function cssVar(result) {
  return { applies: "applies", unknown: "unknown", superseded: "superseded", not_yet_effective: "future", pending: "pending", not_covered: "outside" }[result];
}

function card(h) {
  const level = h.level === "state" ? STATE_NAME[h.jurisdiction] || h.jurisdiction : `City of ${h.jurisdiction.split(",")[0]}`;
  const checks = h.checks && h.checks.length ? `<ul class="checks">${h.checks.map((c) => `<li class="${c.state}">${esc(c.text)}</li>`).join("")}</ul>` : "";
  const conflict = h.conflict_flag && h.conflict_note ? `<div class="conflict"><b>Conflict flagged for review.</b> ${esc(h.conflict_note)}</div>` : "";
  const key = h.key_value ? `<div class="key">${esc(h.key_value)}</div>` : "";
  return `<article class="card ${h.result}">
    <div class="tags"><span class="tag result ${h.result}">${RESULT[h.result].label}</span><span class="tag">${CATEGORY[h.category] || h.category}</span><span class="tag">${esc(level)}</span>${h.reviewed ? '<span class="tag">Human-reviewed</span>' : ""}</div>
    <h3>${esc(h.title)}</h3>
    <p>${esc(h.explanation)}</p>
    ${key}${checks}${conflict}
    <blockquote>“${esc(h.quoted_span)}”</blockquote>
    <div class="provenance"><span>${esc(h.citation)}</span><span>Source ${esc(h.source_doc_id)}, retrieved ${esc(h.retrieved || "n/a")}</span><a href="${esc(h.source_url)}" target="_blank" rel="noopener">Open source</a><span>${esc(h.team_rule_id)}</span></div>
  </article>`;
}

function bindFacts() {
  $("recheck").onclick = () => {
    const extra = {};
    for (const name of ["year_built", "units", "owner_occupied", "public_funding"]) {
      extra[name] = $("f-" + name).value.trim();
    }
    const asOf = $("f-as_of").value;
    if (asOf && asOf !== "2026-10-01") extra.as_of = asOf;
    open(current.address_id, extra);
  };
  $("reset").onclick = () => open(current.address_id);
}

render();
