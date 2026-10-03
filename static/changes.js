const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

fetch("/api/changes").then((r) => r.json()).then((data) => {
  document.getElementById("tests").innerHTML = data.tests.map((test) => `
    <section class="test">
      <div class="id">${esc(test.id)}</div>
      <div>
        <h2>${esc(test.title)}</h2>
        <p>${esc(test.notes)}</p>
        <ul>${test.lines.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
        <p style="margin-top:12px;font-size:14px"><b>Expected by the brief:</b> ${esc(test.expected)}</p>
      </div>
      <div class="nums">
        <b>${test.affected}</b>addresses affected
        <b style="margin-top:12px">${test.flagged}</b>flagged for review
        ${test.met ? '<span class="pass">Expected behavior met</span>' : '<span class="badge review">Check failed</span>'}
      </div>
    </section>`).join("");
});
