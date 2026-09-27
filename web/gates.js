"use strict";

// Fills the worked-example tables under the gate explanations. The numbers
// come from GET /api/gates, which calls the engine's own threshold function,
// so nothing here (or in the HTML) is a typed-in copy of a threshold.
(function () {
  const hosts = document.querySelectorAll("[data-gate-examples]");
  if (!hosts.length) return;

  function cell(tag, text) {
    const el = document.createElement(tag);
    el.textContent = text;
    return el;
  }

  function table(caption, head, rows) {
    const t = document.createElement("table");
    t.className = "gate-example";
    const cap = document.createElement("caption");
    cap.textContent = caption;
    t.appendChild(cap);
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    for (const h of head) hr.appendChild(cell("th", h));
    thead.appendChild(hr);
    t.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const r of rows) {
      const tr = document.createElement("tr");
      for (const c of r) tr.appendChild(cell("td", String(c)));
      tbody.appendChild(tr);
    }
    t.appendChild(tbody);
    return t;
  }

  // constants typed in the notation come from the same response, so the
  // page cannot drift from the configured thresholds
  function fillConstants(data) {
    const p = data.privacy;
    const values = {
      "statistical.floor": data.statistical.floor,
      "privacy.min_population": p.min_population,
      "privacy.max_fraction": p.max_fraction,
      "privacy.max_fraction_words":
        p.max_fraction === 0.5 ? "half" : Math.round(p.max_fraction * 100) + "%",
    };
    for (const el of document.querySelectorAll("[data-gate-const]")) {
      const v = values[el.dataset.gateConst];
      if (v !== undefined) el.textContent = String(v);
    }
  }

  function render(data) {
    fillConstants(data);
    for (const host of hosts) {
      host.textContent = "";
      const scroll = document.createElement("div");
      scroll.className = "table-scroll";
      if (host.dataset.gateExamples === "statistical") {
        scroll.appendChild(table(
          "Reports needed before a group can be named",
          ["Group", "People", "Reports needed"],
          data.statistical.rows.map((r) => [r.scope, r.population, r.required])
        ));
      } else {
        const p = data.privacy;
        scroll.appendChild(table(
          `Minimum ${p.min_population} people; refused once more than ` +
          `${Math.round(p.max_fraction * 100)}% of the group has reported`,
          ["Group", "People", "Big enough to name?", "Refused once reports reach"],
          p.rows.map((r) => [
            r.scope, r.population, r.meets_minimum ? "yes" : "no", r.refused_from,
          ])
        ));
      }
      host.appendChild(scroll);
    }
  }

  async function load(tries) {
    for (let i = 0; i < tries; i++) {
      try {
        const res = await fetch("/api/gates");
        if (res.ok) return render(await res.json());
      } catch (_) { /* retry */ }
      await new Promise((r) => setTimeout(r, 400 * (i + 1)));
    }
    for (const host of hosts) {
      host.textContent = "Worked numbers load from the running server and are unavailable right now.";
    }
  }

  load(4);
})();
