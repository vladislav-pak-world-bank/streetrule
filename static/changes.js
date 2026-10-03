fetch("/api/changes").then((r) => r.json()).then((data) => {
  const root = document.getElementById("tests");
  for (const test of data.tests) {
    const article = document.createElement("article");
    const lines = test.lines.map((line) => `<li>${line}</li>`).join("");
    article.innerHTML = `
      <div class="result">${test.id}</div>
      <h2>${test.title}</h2>
      <p>${test.affected} addresses affected · ${test.flagged} flagged for review</p>
      <p>${test.notes}</p>
      <ul class="plain">${lines}</ul>`;
    root.appendChild(article);
  }
});
