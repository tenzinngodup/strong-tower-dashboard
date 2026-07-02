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
  function escapeHtml(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
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
    // new_leads is a dict {value, total, source, note} as of v3.0
    // (was a plain number previously). Show the weekly additions and use
    // the total as the contextual label.
    const nl = h.new_leads || {};
    const newLeadsVal = (typeof nl === "object") ? (nl.value ?? 0) : (nl || 0);
    const newLeadsNote = (typeof nl === "object" && nl.total)
      ? `of ${nl.total} in pipeline`
      : "active in pipeline";
    setValue("kpi-leads",    fmtCount(newLeadsVal),         newLeadsNote);
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

  // ── Section 1.5: HubSpot pipeline (NEW v3) ────────────────
  // The real B2B pipeline. 244 companies, weekly additions, draft queue.
  function renderPipeline(p) {
    const card = el("pipeline-card");
    if (!card) return;
    const tag = el("pipeline-tag");
    if (!p || !p.available) {
      card.innerHTML = `<p class="empty-state">${p?.reason || "HubSpot pipeline data unavailable. Run build_pipeline_status.py."}</p>`;
      if (tag) { tag.textContent = "unavailable"; tag.className = "section-tag tag-warn"; }
      return;
    }

    const total        = p.total ?? 0;
    const stages       = p.stages || {};
    const drafts       = p.drafts_waiting ?? 0;
    const bySender     = p.drafts_by_sender || {};
    const ready        = p.ready_to_draft ?? 0;
    const withContact  = p.with_contact ?? 0;
    const weekly       = p.weekly_additions || [];
    const batches      = p.batches || {};
    const sampleDrafts = p.sample_drafts || [];

    // Section tag: status summary (v3.5: contacted is now the headline)
    if (tag) {
      const contactedTotal = (stages.contacted_both ?? 0) + (stages.contacted_email_only ?? 0) + (stages.contacted_call_only ?? 0);
      if (contactedTotal > 0) {
        tag.textContent = `${contactedTotal} contacted`;
        tag.className = "section-tag tag-ok";
      } else if (stages.noted && stages.noted > 50) {
        tag.textContent = `${stages.noted} noted`;
        tag.className = "section-tag tag-warn";
      } else if (total > 0) {
        tag.textContent = `${total} cos`;
        tag.className = "section-tag tag-ok";
      } else {
        tag.textContent = "empty";
        tag.className = "section-tag tag-warn";
      }
    }

    // Top alert — leads steven has actually contacted (v3.5)
    let alert = "";
    const contactedTotal = (stages.contacted_both ?? 0) + (stages.contacted_email_only ?? 0) + (stages.contacted_call_only ?? 0);
    if (contactedTotal > 0) {
      const remaining = Math.max(0, Math.round(total * 0.25) - contactedTotal);
      alert = `<div class="fm-alert fm-alert-info">✅ <strong>${contactedTotal} of ${total} companies contacted</strong> ` +
              `(${Math.round(100 * contactedTotal / total)}% of pipeline, target 25% = ${Math.round(total * 0.25)}). ` +
              (remaining > 0
                ? `${remaining} more touches needed to hit the 25% milestone.`
                : `<strong>25% milestone hit.</strong>`) +
              `</div>`;
    } else if (stages.noted && stages.noted > 0) {
      alert = `<div class="fm-alert fm-alert-warn">ℹ️ <strong>${stages.noted} companies</strong> are researched but not yet contacted. ` +
              `Steven can draft and send at ~5-10 per day.</div>`;
    }

    // Stage chips
    const stageChip = (label, val) => {
      const n = Number(val) || 0;
      const klass = n > 0 ? "stat-zero" : "stat-zero";
      return `<div class="stat-block"><div class="stat-num ${klass}">${n.toLocaleString()}</div><div class="stat-label">${label}</div></div>`;
    };

    // Weekly additions sparkline (same pattern as funnel-motion)
    const weeklySpark = (() => {
      if (!weekly.length) return "";
      const vals = weekly.map(w => Number(w.added) || 0);
      const max = Math.max(1, ...vals);
      const w = 280, h = 50, pad = 4;
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
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="50" preserveAspectRatio="xMidYMid meet" class="sparkline">${polyline}${dots}</svg>`;
    })();

    // Weekly list
    const weeklyList = weekly.length
      ? weekly.map(w => {
          const d = (w.week || "").slice(5);  // MM-DD
          return `<li><span class="muted">${d}</span> — added <strong>${w.added}</strong> companies</li>`;
        }).join("")
      : '<li class="muted">No weekly data yet</li>';

    // Batch list
    const batchList = Object.entries(batches)
      .sort((a, b) => b[1] - a[1])
      .map(([name, n]) => `<li><span class="muted">${name}</span> — <strong>${n}</strong> cos</li>`)
      .join("");

    // Sample drafts
    const draftList = sampleDrafts.length
      ? sampleDrafts.map(d =>
          `<li><strong>${escapeHtml(d.company || "?")}</strong> ` +
          `<span class="muted small">[${escapeHtml(d.sender || "?")}]</span><br>` +
          `<span class="small">${escapeHtml(d.subject || "")}</span></li>`
        ).join("")
      : '<li class="muted">No drafts yet</li>';

    card.innerHTML = `
      ${alert}
      <div class="stat-row">
        ${stageChip("Total in pipeline", total)}
        ${stageChip("With contact",      withContact)}
        ${stageChip("Ready to draft",    ready)}
        ${stageChip("Drafts waiting",    drafts)}
      </div>
      <h4>Stages (244-company HubSpot B2B universe)</h4>
      <div class="stat-row">
        ${stageChip("Researched (noted)", stages.noted ?? 0)}
        ${stageChip("Contacted (both)",   stages.contacted_both ?? 0)}
        ${stageChip("Contacted (email)",  stages.contacted_email_only ?? 0)}
        ${stageChip("Contacted (call)",   stages.contacted_call_only ?? 0)}
        ${stageChip("Drafted (not sent)", stages.drafted ?? 0)}
        ${stageChip("Active (legacy)",    stages.active ?? 0)}
        ${stageChip("Lost",               stages.lost ?? 0)}
      </div>
      <h4>Weekly additions</h4>
      ${weeklySpark}
      <ol class="fm-weeks">${weeklyList}</ol>
      <details>
        <summary>By batch (${Object.keys(batches).length} batches)</summary>
        <ol class="fm-weeks">${batchList}</ol>
      </details>
      <details>
        <summary>Sample of ${drafts} drafts in Gmail (${sampleDrafts.length} shown)</summary>
        <ol class="fm-weeks">${draftList}</ol>
      </details>
      <p class="muted small">
        Source: <code>leads/pipeline_master.csv</code> — regenerated by
        <code>scripts/build_pipeline_status.py</code> from 5 HubSpot upload batches
        (master, 06-12, 06-13, 06-17, 06-18) + <code>lead_gen_drafts_log.csv</code>.
        File: ${escapeHtml(p.freshness || "?")}.
      </p>
    `;
  }

  // ── Section 1.52: Outreach by person (NEW v3.1) ───────────
  // Steven (SDR) vs Heber (manager). Per-stage breakdown × per-person.
  // The "outreach_by_person" section pulls from the same pipeline data but
  // slices it by WHO DID the outreach, not just WHO was contacted.
  function renderOutreachByPerson(p) {
    const card = el("obp-card");
    if (!card) return;
    const tag = el("obp-tag");
    if (!p || !p.available) {
      card.innerHTML = `<p class="empty-state">${p?.reason || "Pipeline data unavailable."}</p>`;
      if (tag) { tag.textContent = "unavailable"; tag.className = "section-tag tag-warn"; }
      return;
    }
    const stages  = p.stages || {};
    const byPerson = p.by_person || {};
    const s = byPerson.steven || {};
    const h = byPerson.heber || {};
    const total = (Object.values(stages).reduce((a, b) => a + (Number(b) || 0), 0)) || 0;

    // Per-person stat row
    const sTouched = s.total_touched ?? 0;
    const hTouched = h.total_touched ?? 0;
    const totalTouched = sTouched + hTouched;
    const sPct = total ? Math.round(100 * sTouched / total) : 0;
    const hPct = total ? Math.round(100 * hTouched / total) : 0;

    // Tag
    if (tag) {
      if (sTouched > 0 && hTouched > 0) {
        tag.textContent = `steven ${sTouched} / heber ${hTouched}`;
        tag.className = "section-tag tag-ok";
      } else if (sTouched > 0) {
        tag.textContent = `steven ${sTouched} (sole)`;
        tag.className = "section-tag tag-ok";
      } else {
        tag.textContent = "none contacted";
        tag.className = "section-tag tag-warn";
      }
    }

    // Stage chips (the 6-stage vocabulary)
    const chip = (label, val) => {
      const n = Number(val) || 0;
      return `<div class="stat-block"><div class="stat-num">${n.toLocaleString()}</div><div class="stat-label">${label}</div></div>`;
    };

    // Top companies called list
    const topCalled = p.top_companies || [];

    card.innerHTML = `
      <div class="stat-row">
        ${chip("Total pipeline", total)}
        ${chip("Contacted (any)", (stages.contacted_both ?? 0) + (stages.contacted_email_only ?? 0) + (stages.contacted_call_only ?? 0))}
        ${chip("Drafted (not sent)", stages.drafted ?? 0)}
        ${chip("Noted only", stages.noted ?? 0)}
      </div>
      <h4>Steven (SDR)</h4>
      <div class="stat-row">
        ${chip("Emailed", s.emailed ?? 0)}
        ${chip("Drafted", s.drafted ?? 0)}
        ${chip("Called",  s.called ?? 0)}
        ${chip("Total touched", sTouched)}
        ${chip(`% of pipeline`, `${sPct}%`)}
      </div>
      <h4>Heber (manager)</h4>
      <div class="stat-row">
        ${chip("Emailed", h.emailed ?? 0)}
        ${chip("Drafted", h.drafted ?? 0)}
        ${chip("Total touched", hTouched)}
        ${chip(`% of pipeline`, `${hPct}%`)}
      </div>
      <p class="muted small">
        ${escapeHtml(p.note || "")}
        Heber's drafts go to the <em>legacy</em> gym/dental list (not the 244 HubSpot pipeline).
        His 36 sent emails + 3 replies + 21 bounced (manual stat) are to legacy Apollo outreach (paused May 2026).
      </p>
    `;
  }

  // ── Section 1.54: Phone — per company (NEW v3.1) ─────────
  // Per-company call attribution from call_to_contact_matches.csv.
  // Companion to renderPhoneCall (gross volume). Shows the actual HubSpot
  // companies steven reached.
  function renderPhonePerCompany(p) {
    const card = el("ppc-card");
    if (!card) return;
    const tag = el("ppc-tag");
    if (!p || !p.available) {
      card.innerHTML = `<p class="empty-state">${p?.reason || "Per-company phone data unavailable. Run leads/match_calls.py."}</p>`;
      if (tag) { tag.textContent = "unavailable"; tag.className = "section-tag tag-warn"; }
      return;
    }
    const total          = p.total_calls ?? 0;
    const matched        = p.total_matched ?? 0;
    const unmatched      = p.unmatched_calls ?? 0;
    const connected      = p.connected_matched ?? 0;
    const unmatchConn    = p.unmatched_connected ?? 0;
    const unmatchFailed  = p.unmatched_failed ?? 0;
    const companies      = p.unique_companies ?? 0;
    const contacts       = p.unique_contacts ?? 0;
    const stevenCalls    = p.steven_calls ?? 0;
    const lineOwner      = p.caller_line_owner || "—";
    const topCompanies   = p.top_companies || [];
    const note           = p.note_attribution || "";
    const freshnessH     = p.freshness_hours;
    const matchPct       = total ? Math.round(100 * matched / total) : 0;

    if (tag) {
      if (companies > 0) {
        tag.textContent = `${companies} cos called (${matchPct}% match)`;
        tag.className = "section-tag tag-ok";
      } else {
        tag.textContent = "0 matched";
        tag.className = "section-tag tag-warn";
      }
    }

    // Top 25 companies called (table)
    const rows = topCompanies.map(c => {
      const cName = escapeHtml(c.company_name || "?");
      const cPerson = escapeHtml(c.contact_name || "?");
      const cEmail  = c.contact_email ? escapeHtml(c.contact_email) : "<em class='muted'>no email</em>";
      return `<tr>
        <td>${cName}</td>
        <td>${cPerson}</td>
        <td class="small">${cEmail}</td>
        <td class="num">${c.call_count}</td>
        <td class="num">${c.connected_count}</td>
        <td class="small muted">${escapeHtml((c.first_call || "").slice(0, 10))}</td>
        <td class="small muted">${escapeHtml((c.last_call || "").slice(0, 10))}</td>
      </tr>`;
    }).join("");

    card.innerHTML = `
      <p class="muted small">${escapeHtml(note)}</p>
      <div class="stat-row">
        <div class="stat-block"><div class="stat-num">${total.toLocaleString()}</div><div class="stat-label">Total outbound</div></div>
        <div class="stat-block"><div class="stat-num">${matched.toLocaleString()}</div><div class="stat-label">Matched (${matchPct}%)</div></div>
        <div class="stat-block"><div class="stat-num">${unmatched.toLocaleString()}</div><div class="stat-label">Unmatched (40%)</div></div>
        <div class="stat-block"><div class="stat-num">${companies.toLocaleString()}</div><div class="stat-label">Unique companies</div></div>
        <div class="stat-block"><div class="stat-num">${contacts.toLocaleString()}</div><div class="stat-label">Unique contacts</div></div>
      </div>
      <details>
        <summary>Why the 40% gap? <span class="muted small">(${unmatchConn} unmatched-but-connected + ${unmatchFailed} failed = ${unmatched} total)</span></summary>
        <p class="small">
          Of the ${unmatched} unmatched outbound calls, ${unmatchConn} connected and ${unmatchFailed} failed.
          The connected-but-unmatched calls are real conversations with people whose phone numbers aren't in HubSpot.
          See <code>leads/UNMATCHED_CALLS_ANALYSIS.md</code> for the area-code breakdown (78% of unmatched are
          Portland-local 503 numbers — Steven was working from a phone list that hasn't been imported into HubSpot).
        </p>
      </details>
      <p class="muted small">Zoom line owner: <code>${escapeHtml(lineOwner)}</code> (ext 800) — actual dialer: steven.</p>
      <details${topCompanies.length > 10 ? " open" : ""}>
        <summary>Top ${topCompanies.length} companies by call count (of ${p.all_companies_count} matched total)</summary>
        <table class="data-table">
          <thead>
            <tr><th>Company</th><th>Contact</th><th>Email</th><th class="num">Calls</th><th class="num">Connected</th><th>First</th><th>Last</th></tr>
          </thead>
          <tbody>${rows || '<tr><td colspan="7" class="muted">No matched companies yet</td></tr>'}</tbody>
        </table>
      </details>
      <p class="muted small">Source: <code>leads/call_to_contact_matches.csv</code> — built by
        <code>leads/match_calls.py</code> via E.164 normalization.
        ${freshnessH != null ? `File: ${freshnessH}h old.` : ""}
      </p>
    `;
  }

  // ── Section 1.55: Phone calls (NEW v3.5) ────────────────
  // The Zoom Phone log. Total dials, connect rate, per-day sparkline.
  // Per-company attribution is pending (Zoom masks last-4 of callee).
  function renderPhoneCall(p) {
    const card = el("phone-call-card");
    if (!card) return;
    const tag = el("phone-call-tag");
    if (!p || !p.available) {
      card.innerHTML = `<p class="empty-state">${p?.reason || "Phone call data unavailable. Add leads/phone_call_log.csv."}</p>`;
      if (tag) { tag.textContent = "unavailable"; tag.className = "section-tag tag-warn"; }
      return;
    }

    const total          = p.total_dials ?? 0;
    const connected      = p.connected ?? 0;
    const connectRate    = p.connect_rate ?? 0;
    const totalTalkMin   = p.total_talk_min ?? 0;
    const avgCallSec     = p.avg_call_sec ?? 0;
    const uniqueCallees  = p.unique_callees ?? 0;
    const uniqueConnected = p.unique_connected ?? 0;
    const last7Dials     = p.last_7d_dials ?? 0;
    const last30Dials    = p.last_30d_dials ?? 0;
    const perDay         = p.per_day_14d || [];
    const resultBd       = p.result_breakdown || {};
    const dateRange      = p.date_range || {};

    // Section tag
    if (tag) {
      if (total === 0)            { tag.textContent = "no data";     tag.className = "section-tag tag-warn"; }
      else if (connectRate >= 80) { tag.textContent = "high pickup"; tag.className = "section-tag tag-ok"; }
      else if (connectRate >= 60) { tag.textContent = "active";      tag.className = "section-tag tag-ok"; }
      else                        { tag.textContent = "low pickup";  tag.className = "section-tag tag-warn"; }
    }

    // Per-day sparkline
    const spark = (() => {
      if (!perDay.length) return "";
      const vals = perDay.map(d => Number(d.dials) || 0);
      const max = Math.max(1, ...vals);
      const w = 280, h = 50, pad = 4;
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
      return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="50" preserveAspectRatio="xMidYMid meet" class="sparkline">${polyline}${dots}</svg>`;
    })();

    // Result breakdown chips
    const resultChips = Object.entries(resultBd)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `<span class="chip chip-neutral">${escapeHtml(k)}: ${v}</span>`)
      .join(" ");

    card.innerHTML = `
      <div class="stat-row">
        <div class="stat-block"><div class="stat-num">${total.toLocaleString()}</div><div class="stat-label">Total dials (30d)</div></div>
        <div class="stat-block"><div class="stat-num">${connected.toLocaleString()}</div><div class="stat-label">Connected</div></div>
        <div class="stat-block"><div class="stat-num stat-pos">${connectRate}%</div><div class="stat-label">Connect rate</div></div>
        <div class="stat-block"><div class="stat-num">${totalTalkMin.toFixed(0)}m</div><div class="stat-label">Total talk time</div></div>
        <div class="stat-block"><div class="stat-num">${avgCallSec}s</div><div class="stat-label">Avg call length</div></div>
      </div>
      <h4>Per-day dials (last 14d)</h4>
      ${spark}
      <p class="muted small">Date range: ${escapeHtml(dateRange.first || "?")} → ${escapeHtml(dateRange.last || "?")}. Last 7d: ${last7Dials} dials. Source: leads/phone_call_log.csv (Zoom Phone export).</p>
      <h4>Result breakdown</h4>
      <p>${resultChips || '<span class="muted">no data</span>'}</p>
      <div class="fm-alert fm-alert-warn">
        <strong>Rough estimate:</strong> ${uniqueConnected} unique callee phone numbers connected at least once
        (of ${uniqueCallees} unique callees dialed).
        <strong>The Zoom export masks last-4 digits</strong> of callee phone numbers (e.g. <code>+150****9596</code>),
        so we cannot link these calls to specific HubSpot companies until we fetch HubSpot contact
        phone numbers via Composio MCP. <strong>Plan B in progress.</strong>
      </div>
      <p class="muted small">Note: All 245 calls are from the heber@minyn.link extension (800) — the main company line, not a per-SDR phone system. Calls cannot be attributed to steven vs. miguel vs. anyone else from the Zoom data alone.</p>
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
    renderPipeline(kpis.pipeline || {});          // NEW in v3
    renderOutreachByPerson(kpis.outreach_by_person || {});  // NEW v3.1
    renderPhonePerCompany(kpis.phone_per_company || {});     // NEW v3.1
    renderPhoneCall(kpis.phone_call || {});       // NEW in v3.5
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
