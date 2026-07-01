/* Strong Tower Owner Dashboard — app.
   Single file, no build step, no framework. Fetches kpis.json and renders.
   Failure-tolerant: if a field is missing, we show "—" instead of crashing. */

(function () {
  "use strict";

  // The dashboard page lives in public/ and fetches kpis.json from the same
  // origin. The weekly cron copies data/kpis.json -> public/kpis.json before
  // the page can fetch it. If the fetch fails (404 or 5xx), we render an
  // "old data" warning instead of breaking the layout.
  const KPI_SOURCE = "kpis.json";

  // ── Utilities ────────────────────────────────────────────
  const $  = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  function el(id)  { return document.getElementById(id); }
  function text(t) { return document.createTextNode(t); }

  function fmtMoney(usd) {
    if (usd === null || usd === undefined) return null;
    if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`;
    if (usd >= 10_000)    return `$${Math.round(usd / 1000)}k`;
    if (usd >= 1_000)     return `$${(usd / 1000).toFixed(1)}k`;
    return `$${usd.toFixed(0)}`;
  }
  function fmtCount(n) {
    if (n === null || n === undefined) return null;
    return n.toLocaleString();
  }
  function fmtPct(v) {
    if (v === null || v === undefined) return null;
    return `${v.toFixed(1)}%`;
  }
  function fmtStamp(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleString("en-US", {
        timeZone: "America/Los_Angeles",
        year: "numeric", month: "short", day: "numeric",
        hour: "numeric", minute: "2-digit", timeZoneName: "short",
      });
    } catch { return iso; }
  }
  function setValue(cardId, value, note) {
    const card = el(cardId);
    if (!card) return;
    const valEl = card.querySelector("[data-field='value']");
    const noteEl = card.querySelector("[data-field='note']");
    if (value === null || value === undefined || value === "") {
      valEl.textContent = "—";
      valEl.classList.add("empty");
    } else {
      valEl.textContent = value;
      valEl.classList.remove("empty");
    }
    if (noteEl) noteEl.textContent = note || "";
  }

  // ── Section renderers ────────────────────────────────────
  function renderHeadlines(h) {
    setValue("kpi-pipeline", fmtMoney(h.pipeline_value_usd), "HubSpot open deals");
    setValue("kpi-leads",    fmtCount(h.new_leads),         "active in pipeline");
    if (h.win_rate && h.win_rate.value !== null) {
      setValue("kpi-winrate", fmtPct(h.win_rate.value),
        `${h.win_rate.closed_won} won / ${h.win_rate.closed_lost} lost`);
    } else {
      const wr = h.win_rate || {};
      setValue("kpi-winrate", null,
        `no closed deals yet (${wr.closed_won || 0} won / ${wr.closed_lost || 0} lost)`);
    }
    setValue("kpi-cac", null, h.blended_cac === null
      ? "spend data not yet wired (Phase 1.5)"
      : "");
  }

  function renderMarketing(m) {
    // Cadence.
    const cadence = m.cadence || {};
    for (const ch of ["instagram", "linkedin"]) {
      const row = el(`cadence-${ch}`);
      if (!row) continue;
      const c = cadence[ch] || {};
      row.querySelector(".cadence-count").textContent  = c.posted_7d ?? "—";
      row.querySelector(".cadence-target").textContent = `/ ${c.target_7d ?? "—"}`;
      const badge = row.querySelector(".badge");
      if (c.on_pace) {
        badge.textContent = "on pace";
        badge.className = "badge on-pace";
      } else if (c.posted_7d !== undefined) {
        badge.textContent = "behind";
        badge.className = "badge behind";
      } else {
        badge.textContent = "—";
        badge.className = "badge";
      }
    }
    // Latest post links.
    const latest = m.latest_post || {};
    for (const ch of ["instagram", "linkedin"]) {
      const lp = latest[ch];
      const wrap = el(`latest-${ch}`);
      if (!wrap) continue;
      const a = wrap.querySelector("a");
      if (lp && lp.url) {
        a.href = lp.url;
        const d = lp.time ? new Date(lp.time) : null;
        const when = d ? d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "";
        a.textContent = when ? `${when}` : "view";
      } else {
        a.textContent = "—";
        a.removeAttribute("href");
      }
    }
    // Traffic totals.
    const t = m.traffic || {};
    el("traffic-sessions").textContent  = fmtCount(t.sessions_7d)  ?? "—";
    el("traffic-pageviews").textContent = fmtCount(t.pageviews_7d) ?? "—";

    // By source bars.
    const bySource = t.by_source_7d || {};
    const max = Math.max(1, ...Object.values(bySource).map(v => Number(v) || 0));
    const colors = { instagram: "#d62976", linkedin: "#0a66c2", blog: "#1e4d6b", other: "#6b7280" };
    const sb = el("source-bars");
    sb.innerHTML = "";
    if (Object.keys(bySource).length === 0) {
      sb.innerHTML = '<p class="empty-state">No source data</p>';
    } else {
      for (const [src, n] of Object.entries(bySource)) {
        const pct = Math.max(2, (Number(n) / max) * 100);
        const row = document.createElement("div");
        row.className = "source-bar";
        row.innerHTML = `
          <span class="source-bar-label">${src}</span>
          <div class="source-bar-track"><div class="source-bar-fill" style="width:${pct}%;background:${colors[src] || colors.other}"></div></div>
          <span class="source-bar-num">${n}</span>
        `;
        sb.appendChild(row);
      }
    }
    // Top pages.
    const tp = el("top-pages");
    tp.innerHTML = "";
    if (!t.top_pages_7d || t.top_pages_7d.length === 0) {
      tp.innerHTML = '<li class="muted">No data</li>';
    } else {
      for (const p of t.top_pages_7d) {
        const li = document.createElement("li");
        const path = p.pagePath || "/";
        const sess = p.sessions || 0;
        li.innerHTML = `<code>${path}</code><span class="sessions">${sess} sessions</span>`;
        tp.appendChild(li);
      }
    }
  }

  function renderSales(s) {
    const funnel = s.funnel || {};
    const order = ["New", "Contacted", "Walkthrough", "Quoted", "Won"];
    const max = Math.max(1, ...order.map(k => Number(funnel[k]) || 0));
    const colors = { New: "#94a3b8", Contacted: "#60a5fa", Walkthrough: "#a78bfa", Quoted: "#fbbf24", Won: "#15803d" };
    const f = el("funnel");
    f.innerHTML = "";
    if (order.every(k => !funnel[k])) {
      f.innerHTML = '<p class="empty-state">No funnel data</p>';
      return;
    }
    for (const k of order) {
      const count = Number(funnel[k]) || 0;
      if (count === 0) continue;  // skip empty stages
      const pct = Math.max(8, (count / max) * 100);
      const row = document.createElement("div");
      row.className = "funnel-row";
      row.style.background = colors[k] || "#94a3b8";
      row.style.width = `${pct}%`;
      row.innerHTML = `<span class="funnel-label">${k}</span><span class="funnel-count">${count}</span>`;
      f.appendChild(row);
    }
    // Summary line: top-of-funnel + total in motion.
    const newCount      = Number(funnel.New) || 0;
    const contactedCount= Number(funnel.Contacted) || 0;
    const wonCount      = Number(funnel.Won) || 0;
    const total         = newCount + contactedCount + wonCount;
    el("funnel-summary").innerHTML =
      `<span><strong>${newCount}</strong> new</span>` +
      `<span><strong>${contactedCount}</strong> contacted</span>` +
      `<span><strong>${wonCount}</strong> won</span>` +
      `<span class="muted">(${total} total in funnel)</span>`;
  }

  function renderCustomer(c) {
    const card = el("customer-card");
    if (!c.available) {
      card.innerHTML = `<p class="empty-state">${c.note || c.reason || "Customer metrics not yet available."}</p>
                        <p class="muted small">HubSpot currently shows 0 closed-won deals. Once the first deal is closed-won, this card will display MRR + account count.</p>`;
      return;
    }
    card.innerHTML = `
      <div class="stat-row">
        <div class="stat-block">
          <div class="stat-num">${fmtCount(c.won_count) ?? "—"}</div>
          <div class="stat-label">Active customers</div>
        </div>
        <div class="stat-block">
          <div class="stat-num">${fmtMoney(c.won_value_usd) ?? "—"}</div>
          <div class="stat-label">Total won</div>
        </div>
        <div class="stat-block">
          <div class="stat-num">${fmtCount(c.active_pipeline) ?? "—"}</div>
          <div class="stat-label">In active pipeline</div>
        </div>
      </div>
    `;
  }

  function renderActions(actions) {
    const list = el("actions-list");
    list.innerHTML = "";
    if (!actions || actions.length === 0) {
      list.innerHTML = '<p class="empty-state">No action items this period. ✅</p>';
      return;
    }
    // Sort: high first, then medium, then low.
    const sev = { high: 0, medium: 1, low: 2 };
    actions.sort((a, b) => (sev[a.severity] ?? 9) - (sev[b.severity] ?? 9));
    for (const a of actions) {
      const div = document.createElement("div");
      div.className = `action-item severity-${a.severity || "low"}`;
      div.innerHTML = `
        <div class="action-item-title">${a.title || "(untitled)"}<span class="action-item-source">${a.source || ""}</span></div>
        <div class="action-item-detail">${a.detail || ""}</div>
      `;
      list.appendChild(div);
    }
  }

  // ── Main: fetch + render ─────────────────────────────────
  function showError(msg) {
    el("data-stamp-text").textContent = msg;
    el("footer-stamp").textContent    = "Data unavailable";
  }

  async function main() {
    let kpis;
    try {
      const r = await fetch(KPI_SOURCE, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      kpis = await r.json();
    } catch (e) {
      console.error("Failed to fetch kpis.json:", e);
      showError("⚠ Data unavailable — see footer");
      // Render headers/footers with whatever info we have.
      el("footer-stamp").textContent = `Last attempt: ${new Date().toLocaleString()}`;
      return;
    }

    el("data-stamp-text").textContent = `Data as of ${fmtStamp(kpis.computed_at)}`;
    el("footer-stamp").textContent    = `Last updated ${fmtStamp(kpis.computed_at)}`;

    renderHeadlines(kpis.headlines || {});
    renderMarketing(kpis.marketing || {});
    renderSales(kpis.sales || {});
    renderCustomer(kpis.customer || {});
    renderActions(kpis.actions || []);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", main);
  } else {
    main();
  }
})();
