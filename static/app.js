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
  result.innerHTML = `<h1>${label}</h1><p class="cite">Legal city ${facts.join(" · ")} · as of ${data.as_of}</p>${cards}`;
}

function card(hit) {
  return `<article>
    <div class="result">${hit.result.replaceAll("_", " ")}</div>
    <h2>${hit.title || hit.category}</h2>
    <p>${hit.explanation}</p>
    <p class="cite">${hit.citation || ""}</p>
    <p class="quote">${hit.quoted_span || ""}</p>
  </article>`;
}
