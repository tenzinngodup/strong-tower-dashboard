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

  // ── Funnel motion (NEW in v2) ──────────────────────────────────
  // Renders weekly pipeline trend + auto-action callouts.
  // Tells the owner at a glance: is the pipeline moving or frozen?
  function renderFunnelMotion(fm) {
    const card = el("funnel-motion-card");
    if (!card) return;
    const tag = el("funnel-motion-tag");
    if (!fm || !fm.available) {
      card.innerHTML = `<p class="empty-state">${fm?.reason || "Funnel-motion data unavailable."}</p>`;
      if (tag) { tag.textContent = "unavailable"; tag.className = "section-tag tag-warn"; }
      return;
    }

    const totals = fm.totals_current || {};
    const delta  = fm.this_week_delta || {};
    const trend  = fm.trend || [];
    const isFrozen = !!fm.frozen;
    const weeksSinceOutreach = fm.weeks_since_outreach;

    // Section tag reflects state: green=ok, red=frozen, amber=stale
    if (tag) {
      if (isFrozen) { tag.textContent = "frozen"; tag.className = "section-tag tag-warn"; }
      else if (weeksSinceOutreach != null && weeksSinceOutreach >= 1) { tag.textContent = "stale"; tag.className = "section-tag tag-warn"; }
      else { tag.textContent = "moving"; tag.className = "section-tag tag-ok"; }
    }

    // Mini sparkline (SVG) for the active count over the trend window.
    const spark = (col) => {
      if (!trend.length) return "";
      const vals = trend.map(t => Number(t[col]) || 0);
      const max = Math.max(1, ...vals);
      const w = 280, h = 60, pad = 4;
      const step = vals.length > 1 ? (w - 2 * pad) / (vals.length - 1) : 0;
      const points = vals.map((v, i) => {
        const x = pad + i * step;
        const y = h - pad - (v / max) * (h - 2 * pad);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      });
      const polyline = `<polyline points="${points.join(' ')}" fill="none" stroke="currentColor" stroke-width="2" />`;
      const dots = points.map(p => {
        const [cx, cy] = p.split(",");
        return `<circle cx="${cx}" cy="${cy}" r="3" fill="currentColor" />`;
      }).join("");
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="60" preserveAspectRatio="xMidYMid meet" class="sparkline">${polyline}${dots}</svg>`;
    };

    // This-week chips. We render each as a stat-block; if delta is 0 we
    // surface that fact explicitly (not silently as "no change"). Counts
    // here are NEUTRAL by design — the dashboard doesn't know whether
    // more "lost" is good or bad, so we don't color them green.
    const chip = (label, val) => {
      const n = Number(val) || 0;
      const klass = n > 0 ? "stat-pos" : "stat-zero";
      return `<div class="stat-block"><div class="stat-num ${klass}">${n.toLocaleString()}</div><div class="stat-label">${label}</div></div>`;
    };
    // For funnel-motion's totals row we use a neutral color (always grey)
    // because the dashboard can't interpret direction: more "lost" or
    // more "active" is not inherently positive.
    const neutralChip = (label, val) => {
      const n = Number(val) || 0;
      return `<div class="stat-block"><div class="stat-num stat-zero">${n.toLocaleString()}</div><div class="stat-label">${label}</div></div>`;
    };

    const weeksList = trend.length
      ? trend.map(t => {
          const d = (t.date || "").slice(5);  // MM-DD
          return `<li><span class="muted">${d}</span> ` +
                 `active <strong>${t.active}</strong> · ` +
                 `contacted <strong>${t.contacted}</strong> · ` +
                 `sent <strong>${t.sent}</strong> · ` +
                 `hs_new <strong>${t.hubspot_new}</strong></li>`;
        }).join("")
      : '<li class="muted">No weekly snapshots in leads_history.csv yet</li>';

    let alert = "";
    if (isFrozen) {
      alert = `<div class="fm-alert fm-alert-warn">⚠️ Pipeline counts unchanged for 3+ weeks — ` +
              `active=${totals.active}, contacted=${totals.contacted}, won=${totals.won}, lost=${totals.lost}. ` +
              `Either no outreach happened, or the data isn't being recorded.</div>`;
    } else if (weeksSinceOutreach != null && weeksSinceOutreach >= 1) {
      alert = `<div class="fm-alert fm-alert-info">ℹ️ SDR has not sent outreach in ${weeksSinceOutreach} week(s).</div>`;
    }

    card.innerHTML = `
      ${alert}
      <div class="stat-row">
        ${neutralChip("Active",    totals.active)}
        ${neutralChip("Contacted", totals.contacted)}
        ${neutralChip("Won",       totals.won)}
        ${neutralChip("Lost",      totals.lost)}
      </div>
      <h4>This week</h4>
      <div class="stat-row">
        ${chip("New active",    delta.new_active)}
        ${chip("New contacted", delta.new_contacted)}
        ${chip("Sent",          delta.sent)}
        ${chip("HubSpot new",   delta.hubspot_new)}
      </div>
      <h4>Trend (last ${trend.length} weeks)</h4>
      <div class="sparkline-row">
        <div class="sparkline-block">
          <div class="sparkline-label">active</div>
          ${spark("active")}
        </div>
        <div class="sparkline-block">
          <div class="sparkline-label">sent</div>
          ${spark("sent")}
        </div>
        <div class="sparkline-block">
          <div class="sparkline-label">hubspot_new</div>
          ${spark("hubspot_new")}
        </div>
      </div>
      <details>
        <summary>Weekly snapshots</summary>
        <ol class="fm-weeks">${weeksList}</ol>
      </details>
      <p class="muted small">Source: <code>leads/email_status.csv</code> (SDR weekly log) — ` +
        `${fm.days_since_last ?? "?"} day(s) since last entry.</p>
    `;
  }

  // ── Outreach (NEW in v2) ───────────────────────────────────────
  // Renders SDR sent-email volume + bounce signal from the Gmail source.
  function renderOutreach(o) {
    const card = el("outreach-card");
    const tag = el("outreach-tag");
    if (!card) return;
    if (!o || !o.available) {
      card.innerHTML = `<p class="empty-state">${o?.reason || "Outreach data unavailable."}</p>`;
      if (tag) { tag.textContent = "unavailable"; tag.className = "section-tag tag-warn"; }
      return;
    }
    const sent = Number(o.sent) || 0;
    const perDay = Number(o.per_day_avg) || 0;
    const bounced = Number(o.bounced_est) || 0;
    const bounceRate = Number(o.bounce_rate) || 0;
    const byDay = o.by_day || [];

    // Tag reflects state
    if (tag) {
      if (sent === 0)              { tag.textContent = "no sends"; tag.className = "section-tag tag-warn"; }
      else if (bounceRate > 5)     { tag.textContent = "high bounce"; tag.className = "section-tag tag-warn"; }
      else                          { tag.textContent = "active"; tag.className = "section-tag tag-ok"; }
    }

    // Sparkline of per-day sends
    const spark = (() => {
      if (!byDay.length) return "";
      const vals = byDay.map(d => Number(d.sent) || 0);
      const max = Math.max(1, ...vals);
      const w = 280, h = 60, pad = 4;
      const step = vals.length > 1 ? (w - 2 * pad) / (vals.length - 1) : 0;
      const points = vals.map((v, i) => {
        const x = pad + i * step;
        const y = h - pad - (v / max) * (h - 2 * pad);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      });
      const polyline = `<polyline points="${points.join(' ')}" fill="none" stroke="currentColor" stroke-width="2" />`;
      const dots = points.map(p => {
        const [cx, cy] = p.split(",");
        return `<circle cx="${cx}" cy="${cy}" r="3" fill="currentColor" />`;
      }).join("");
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="60" preserveAspectRatio="xMidYMid meet" class="sparkline">${polyline}${dots}</svg>`;
    })();

    const chip = (label, val) => {
      const n = Number(val) || 0;
      const klass = n > 0 ? "stat-pos" : "stat-zero";
      return `<div class="stat-block"><div class="stat-num ${klass}">${n.toLocaleString()}</div><div class="stat-label">${label}</div></div>`;
    };

    const daysList = byDay.length
      ? byDay.map(d => {
          const date = d.date || "";
          return `<li><span class="muted">${date}</span> — <strong>${d.sent}</strong> sent</li>`;
        }).join("")
      : '<li class="muted">No sends in window (only 20 most recent hydrated for the sparkline)</li>';

    let replyNote = "";
    if (!o.replies_available) {
      replyNote = `<p class="muted small">ℹ️ ${o.replies_note || "Reply counts not yet wired (v2.1)."}</p>`;
    }

    card.innerHTML = `
      <div class="stat-row">
        ${chip(`Sent (${o.window_days || 14}d)`, sent)}
        ${chip("Per day avg", perDay)}
        ${chip("Bounced (est)", bounced)}
        ${chip("Bounce rate", `${bounceRate}%`)}
      </div>
      <h4>By day (hydrated sample of 20 most recent)</h4>
      <div class="sparkline-row">
        <div class="sparkline-block">
          <div class="sparkline-label">sends / day</div>
          ${spark}
        </div>
      </div>
      <details>
        <summary>Days with sends</summary>
        <ol class="fm-weeks">${daysList}</ol>
      </details>
      <p class="muted small">Source: <code>steven@strongtowercs.com</code> (Composio → Gmail API) — ${o.window_start} to ${o.window_end}.</p>
      ${replyNote}
    `;
  }

  // ── Engagement (NEW in v2) ──────────────────────────────────
  // Renders HubSpot call/meeting/email volume. Tells the owner
  // whether contacts engage after outreach, and whether walkthroughs
  // are being booked.
  function renderEngagement(e) {
    const card = el("engagement-card");
    const tag = el("engagement-tag");
    if (!card) return;
    if (!e || !e.available) {
      card.innerHTML = `<p class="empty-state">${e?.reason || "Engagement data unavailable."}</p>`;
      if (tag) { tag.textContent = "unavailable"; tag.className = "section-tag tag-warn"; }
      return;
    }

    const calls    = e.calls    || { in_window: 0, per_day: [] };
    const meetings = e.meetings || { in_window: 0, per_day: [] };
    const emails   = e.emails   || { in_window: 0, per_day: [] };

    // Tag reflects state: green=meeting booked, red=no meetings, amber=low
    if (tag) {
      if (meetings.in_window === 0) { tag.textContent = "no walkthroughs"; tag.className = "section-tag tag-warn"; }
      else if (calls.in_window < 5) { tag.textContent = "low"; tag.className = "section-tag tag-warn"; }
      else { tag.textContent = "active"; tag.className = "section-tag tag-ok"; }
    }

    const chip = (label, val) => {
      const n = Number(val) || 0;
      const klass = n > 0 ? "stat-pos" : "stat-zero";
      return `<div class="stat-block"><div class="stat-num ${klass}">${n.toLocaleString()}</div><div class="stat-label">${label}</div></div>`;
    };

    // Sparkline helper (reused pattern from other sections)
    const spark = (perDay) => {
      if (!perDay || !perDay.length) return "";
      const vals = perDay.map(d => Number(d.count) || 0);
      const max = Math.max(1, ...vals);
      const w = 280, h = 60, pad = 4;
      const step = vals.length > 1 ? (w - 2 * pad) / (vals.length - 1) : 0;
      const points = vals.map((v, i) => {
        const x = pad + i * step;
        const y = h - pad - (v / max) * (h - 2 * pad);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      });
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="60" preserveAspectRatio="xMidYMid meet" class="sparkline">` +
        `<polyline points="${points.join(' ')}" fill="none" stroke="currentColor" stroke-width="2" />` +
        points.map(p => {
          const [cx, cy] = p.split(",");
          return `<circle cx="${cx}" cy="${cy}" r="3" fill="currentColor" />`;
        }).join("") +
        `</svg>`;
    };

    const daysTable = (perDay) => {
      if (!perDay || !perDay.length) return '<li class="muted">No data in window</li>';
      return perDay.map(d =>
        `<li><span class="muted">${d.date}</span> — <strong>${d.count}</strong></li>`
      ).join("");
    };

    let alert = "";
    if (meetings.in_window === 0 && calls.in_window > 0) {
      alert = `<div class="fm-alert fm-alert-warn">⚠️ ${calls.in_window} calls logged but 0 walkthroughs booked in 14d. ` +
              `Either no contacted lead has advanced, or walkthroughs are happening off-HubSpot.</div>`;
    }

    card.innerHTML = `
      ${alert}
      <div class="stat-row">
        ${chip("Calls (14d)", calls.in_window)}
        ${chip("Meetings (14d)", meetings.in_window)}
        ${chip("Emails (14d)", emails.in_window)}
      </div>
      <h4>Activity timeline (14d)</h4>
      <div class="sparkline-row">
        <div class="sparkline-block">
          <div class="sparkline-label">calls / day</div>
          ${spark(calls.per_day)}
        </div>
        <div class="sparkline-block">
          <div class="sparkline-label">emails / day</div>
          ${spark(emails.per_day)}
        </div>
      </div>
      <details>
        <summary>Day-by-day breakdown</summary>
        <h5 style="margin-top:8px;font-size:11px;color:var(--c-muted);text-transform:uppercase;">Calls</h5>
        <ol class="fm-weeks">${daysTable(calls.per_day)}</ol>
        <h5 style="margin-top:8px;font-size:11px;color:var(--c-muted);text-transform:uppercase;">Meetings</h5>
        <ol class="fm-weeks">${daysTable(meetings.per_day)}</ol>
        <h5 style="margin-top:8px;font-size:11px;color:var(--c-muted);text-transform:uppercase;">Emails</h5>
        <ol class="fm-weeks">${daysTable(emails.per_day)}</ol>
      </details>
      <p class="muted small">Source: HubSpot CRM (calls, meetings, emails object types) — ${e.window_start} to ${e.window_end}. Per-call duration and disposition not yet wired (v2.1, pending Composio MCP fix).</p>
    `;
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
    renderFunnelMotion(kpis.funnel_motion || {});   // NEW in v2
    renderOutreach(kpis.outreach || {});            // NEW in v2
    renderEngagement(kpis.engagement || {});        // NEW in v2
    renderCustomer(kpis.customer || {});
    renderActions(kpis.actions || []);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", main);
  } else {
    main();
  }
})();
