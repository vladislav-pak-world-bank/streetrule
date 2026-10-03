const q = document.getElementById("q");
const matches = document.getElementById("matches");
const result = document.getElementById("result");

fetch("/api/health").then((r) => r.json()).then((h) => {
  document.getElementById("health").textContent = h.rules
    ? `${h.rules} rules extracted`
    : "Rules not extracted yet";
});

let timer;
q.addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(search, 150);
});

async function search() {
  const text = q.value.trim();
  matches.innerHTML = "";
  if (text.length < 2) return;
  const rows = await fetch("/api/addresses?q=" + encodeURIComponent(text)).then((r) => r.json());
  for (const row of rows) {
    const li = document.createElement("li");
    li.textContent = row.label;
    li.onclick = () => openAddress(row.address_id, row.label);
    matches.appendChild(li);
  }
}

async function openAddress(id, label) {
  matches.innerHTML = "";
  q.value = label;
  const data = await fetch("/api/lookup?address_id=" + id).then((r) => r.json());
  const facts = [data.legal_city + ", " + data.state];
  if (data.year_built) facts.push("built " + data.year_built);
  if (data.units) facts.push(data.units + " units");
  const cards = data.hits.length
    ? data.hits.map(card).join("")
    : "<p>No rule in the six categories matched this jurisdiction.</p>";
  result.innerHTML = `<h1>${label}</h1><p class="cite">Legal city ${facts.join(" · ")} · as of ${data.as_of}</p>${cards}${gaps(data.gaps)}`;
}

function gaps(list) {
  if (!list || !list.length) return "";
  const links = list.map((g) => `<li><a href="${g.url}" target="_blank" rel="noopener">${g.doc_id}</a></li>`).join("");
  return `<article class="gap">
    <div class="result">unknown</div>
    <h2>Sources we could not read</h2>
    <p>These sources cover this place, but their text was not in our corpus. Rules in them are not shown above. Check them directly.</p>
    <ul>${links}</ul>
  </article>`;
}

function card(hit) {
  return `<article>
    <div class="result">${hit.result.replaceAll("_", " ")}</div>
    <h2>${hit.title || hit.category}</h2>
    <p>${hit.explanation}</p>
    ${hit.conflict_flag && hit.conflict_note ? `<p class="conflict">Conflict: ${hit.conflict_note}</p>` : ""}
    <p class="cite">${hit.citation || ""}${hit.source_url ? ` · <a href="${hit.source_url}" target="_blank" rel="noopener">source</a>` : ""}</p>
    <p class="quote">${hit.quoted_span || ""}</p>
  </article>`;
}
