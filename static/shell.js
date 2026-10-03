/* Shared chrome: jump-to-address, and a small confirmation when a link is copied. */
(function () {
  const mac = /Mac|iPhone|iPad/.test(navigator.platform);
  document.querySelectorAll(".kbd").forEach((el) => {
    el.textContent = mac ? "⌘K" : "Ctrl K";
  });

  const palette = document.createElement("div");
  palette.id = "palette";
  palette.className = "palette hidden";
  palette.innerHTML = `
    <div class="palette-box" role="dialog" aria-modal="true" aria-label="Jump to an address">
      <input id="palette-q" placeholder="Jump to a street, a city, or an id" autocomplete="off" aria-label="Address">
      <ul id="palette-list"></ul>
      <p class="palette-hint">Arrow keys move. Enter opens. Esc closes.</p>
    </div>`;
  document.body.appendChild(palette);

  const toast = document.createElement("div");
  toast.id = "toast";
  toast.className = "toast";
  toast.setAttribute("role", "status");
  document.body.appendChild(toast);

  const input = palette.querySelector("input");
  const list = palette.querySelector("ul");
  let options = [];
  let cursor = -1;
  let timer;

  function openPalette() {
    palette.classList.remove("hidden");
    input.value = "";
    list.innerHTML = "";
    options = [];
    cursor = -1;
    setTimeout(() => input.focus(), 20);
  }

  function closePalette() {
    palette.classList.add("hidden");
  }

  function choose(id) {
    closePalette();
    if (location.pathname === "/" && typeof window.streetOpen === "function") window.streetOpen(id);
    else location.assign("/?a=" + encodeURIComponent(id));
  }

  const pretty = (value) => String(value || "").toLowerCase().replace(/(^|[\s\-./])([a-z])/g, (m, gap, letter) => gap + letter.toUpperCase());
  const prettyLabel = (label) => {
    const parts = String(label).split(", ");
    const state = parts.length > 1 ? parts.pop() : "";
    const body = parts.map(pretty).join(", ");
    return state ? `${body}, ${state}` : body;
  };

  function paint() {
    list.innerHTML = options.map((o, i) => {
      const label = prettyLabel(o.label).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
      return `<li class="${i === cursor ? "active" : ""}" data-goto="${o.address_id}">${label}</li>`;
    }).join("");
  }

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      palette.classList.contains("hidden") ? openPalette() : closePalette();
      return;
    }
    if (event.key === "Escape") closePalette();
    if (!palette.classList.contains("hidden")) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (event.key === "/" && !typing) {
      const search = document.getElementById("q");
      if (search) { event.preventDefault(); search.focus(); }
    }
  });

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const text = input.value.trim();
      options = [];
      cursor = -1;
      if (text.length < 2) { list.innerHTML = ""; return; }
      options = await fetch("/api/addresses?q=" + encodeURIComponent(text)).then((r) => r.json());
      cursor = options.length ? 0 : -1;
      paint();
    }, 100);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") { cursor = Math.min(cursor + 1, options.length - 1); paint(); event.preventDefault(); }
    else if (event.key === "ArrowUp") { cursor = Math.max(cursor - 1, 0); paint(); event.preventDefault(); }
    else if (event.key === "Enter" && options.length) { choose(options[Math.max(cursor, 0)].address_id); event.preventDefault(); }
  });

  palette.addEventListener("click", (event) => {
    const item = event.target.closest("[data-goto]");
    if (item) choose(item.dataset.goto);
    else if (event.target === palette) closePalette();
  });

  const opener = document.getElementById("open-palette");
  if (opener) opener.addEventListener("click", openPalette);

  let toastTimer;
  window.streetToast = (message) => {
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  };
})();
