// ================================================================
// PTC ANALYZER — Path to Conversion (CM360)
// Módulo aislado, cargado solo si dashboard_cfg.ptc_analyzer.enabled
// (ver ?action=me → ptcEnabled en main.py).
// Reutiliza las globals de dashboard-final.html (gasGet, esc, showToast)
// — se carga como <script> en la misma página, comparte scope global.
// ================================================================

(function () {
  let _ptcLoaded = false;
  let _ptcResult = null;
  let _ptcConvs = null;
  let _ptcCharts = {};
  let _ptcFerias = [];
  let _ptcSelFerias = new Set();
  let _ptcFeriaActive = false;

  const CHAN_COL = { Search: '#1a73e8', Display: '#f9ab00', Video: '#ea4335' };
  const CHAN_COLS = CHAN_COL;
  const SITE_PALETTE = ['#1a73e8', '#f9ab00', '#ea4335', '#0098A6', '#8b5cf6', '#1e8e3e', '#f97316', '#06b6d4', '#e11d48', '#84cc16'];

  // ── STYLE (inyectado una vez, prefijo .ptc- para no chocar con el resto) ──
  function injectStyle() {
    if (document.getElementById('ptc-analyzer-style')) return;
    const css = `
      .ptc-wrap{padding:4px 0}
      .ptc-kpi-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:22px}
      .ptc-kpi{background:var(--s1);border:1px solid var(--border);border-radius:6px;padding:14px 16px;border-left:4px solid var(--llyc-teal)}
      .ptc-kpi-label{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px}
      .ptc-kpi-val{font-size:22px;font-weight:700;line-height:1}
      .ptc-kpi-sub{font-size:11px;color:var(--muted2);margin-top:6px}
      .ptc-sec-lbl{font-family:'DM Mono',monospace;font-size:9px;color:var(--llyc-teal);text-transform:uppercase;letter-spacing:1px;margin-top:26px;margin-bottom:2px}
      .ptc-sec-title{font-size:17px;font-weight:700;margin-bottom:4px}
      .ptc-sec-desc{font-size:12px;color:var(--muted2);margin-bottom:14px;line-height:1.4}
      .ptc-g2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
      .ptc-g21{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-bottom:12px}
      .ptc-card{background:var(--s1);border:1px solid var(--border);border-radius:6px;padding:16px}
      .ptc-card-title{font-size:13px;font-weight:700;margin-bottom:3px}
      .ptc-card-sub{font-size:11px;color:var(--muted);margin-bottom:10px}
      .ptc-card canvas{max-width:100%;display:block}
      .ptc-insight{background:rgba(54,167,183,0.08);border:1px solid var(--border2);border-radius:6px;padding:12px 14px;margin-top:14px;display:flex;gap:10px;align-items:flex-start}
      .ptc-ins-txt{font-size:12px;color:var(--muted2);line-height:1.6}
      .ptc-syn-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
      .ptc-syn-card{background:var(--s2);border-radius:6px;padding:12px;text-align:center}
      .ptc-syn-pct{font-size:24px;font-weight:700;margin-bottom:4px}
      .ptc-syn-desc{font-size:11px;color:var(--muted);line-height:1.4}
      .ptc-tbl-wrap{overflow-x:auto}
      .ptc-tbl{width:100%;border-collapse:collapse;font-size:12px}
      .ptc-tbl th{background:var(--s2);color:var(--muted2);padding:8px 12px;text-align:left;font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:0.5px}
      .ptc-tbl td{padding:7px 12px;border-bottom:1px solid var(--border);color:var(--text)}
      .ptc-tbl tr:last-child td{border-bottom:none}
      .ptc-nr{text-align:right;font-family:'DM Mono',monospace;font-size:11px}
      .ptc-nb{text-align:right;font-family:'DM Mono',monospace;font-size:11px;font-weight:700}
      .ptc-rate-bar{width:100%;height:5px;background:var(--border);border-radius:3px;overflow:hidden;margin-top:3px}
      .ptc-rate-fill{height:100%;border-radius:3px;background:var(--llyc-teal)}
      .ptc-bb-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
      .ptc-bb-card{border-radius:6px;padding:16px;border:2px solid var(--border)}
      .ptc-bb-card.b2b{border-color:#1a73e8;background:rgba(26,115,232,0.08)}
      .ptc-bb-card.b2c{border-color:#1e8e3e;background:rgba(30,142,62,0.08)}
      .ptc-bb-lbl{font-family:'DM Mono',monospace;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}
      .ptc-bb-big{font-size:28px;font-weight:700;margin-bottom:4px}
      .ptc-path-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)}
      .ptc-path-row:last-child{border-bottom:none}
      .ptc-path-pct{font-size:12px;font-weight:700;min-width:42px;color:var(--muted2)}
      .ptc-path-tag{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700;white-space:nowrap}
      .ptc-pill-search{background:rgba(26,115,232,.18);color:#5b9bf0}
      .ptc-pill-display{background:rgba(245,158,11,.18);color:#e5a94a}
      .ptc-pill-video{background:rgba(220,38,38,.18);color:#e5646a}
      .ptc-pill-other{background:rgba(124,58,237,.18);color:#a78bfa}
      .ptc-pill-rm{background:rgba(16,185,129,.18);color:#4ade80}
      .ptc-path-arrow{color:var(--muted);font-size:12px;margin:0 1px}
      .ptc-path-mult{color:var(--muted);font-size:11px;font-weight:700;margin:0 1px}
      .ptc-path-channels{display:flex;gap:4px;align-items:center;flex-wrap:wrap;flex:1}
      .ptc-path-bar-wrap{flex:0 0 80px;height:4px;background:var(--border);border-radius:2px;margin:0 8px}
      .ptc-path-bar{height:4px;border-radius:2px}
      .ptc-path-n{font-size:11px;color:var(--muted);min-width:38px;text-align:right;font-family:'DM Mono',monospace}
      .ptc-device-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;font-size:12px;color:var(--text)}
      .ptc-device-dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px}
      .ptc-note{background:rgba(245,73,99,0.08);border:1px solid rgba(245,73,99,0.25);border-radius:6px;padding:10px 14px;margin-bottom:18px;font-size:11px;color:var(--muted2);display:flex;gap:8px}
      .ptc-loading{padding:60px 0;text-align:center;color:var(--muted)}
      .ptc-feria-box{background:var(--s1);border:1px solid var(--border);border-radius:6px;padding:12px 14px;margin-bottom:16px}
      .ptc-feria-chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
      .ptc-fc{padding:4px 11px;border-radius:14px;font-size:11px;font-weight:700;cursor:pointer;border:1.5px solid var(--border);background:var(--s2);color:var(--muted);transition:all .15s;user-select:none}
      .ptc-fc.on{background:var(--llyc-teal);border-color:var(--llyc-teal);color:#04141c}
      .ptc-pptx-row{background:var(--s1);border:1px solid var(--border);border-radius:6px;padding:16px 18px;margin-top:22px;display:flex;align-items:center;justify-content:space-between}
      .ptc-pptx-btn{background:var(--llyc-red);color:#fff;border:none;padding:9px 18px;border-radius:4px;font-family:'Montserrat',sans-serif;font-weight:700;font-size:12px;cursor:pointer;transition:all .15s}
      .ptc-pptx-btn:hover{background:var(--llyc-teal)}
      .ptc-pptx-btn:disabled{opacity:.5;cursor:not-allowed}
    `;
    const styleEl = document.createElement('style');
    styleEl.id = 'ptc-analyzer-style';
    styleEl.textContent = css;
    document.head.appendChild(styleEl);
  }

  function ensureExternalScripts() {
    const need = [];
    if (typeof Chart === 'undefined') {
      need.push('https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js');
    }
    if (typeof PptxGenJS === 'undefined') {
      need.push('https://cdn.jsdelivr.net/npm/pptxgenjs@3.12.0/dist/pptxgen.bundle.js');
    }
    return Promise.all(
      need.map(
        (src) =>
          new Promise((resolve) => {
            const s = document.createElement('script');
            s.src = src;
            s.onload = resolve;
            s.onerror = resolve;
            document.head.appendChild(s);
          })
      )
    );
  }

  // ── ADAPTADOR: filas BQ (headers+rows) → conversiones (buildConv) ──
  // NO reutiliza processLong() del analyzer original tal cual porque:
  // - IFEMA numera InteractionNumber desde 0 (CM360 estándar desde 1) —
  //   buildConv ya tolera esto (fallback a min-order), pero el filtro
  //   original `order>0` descartaría el last-touch real (order=0).
  // - No existe fila "summary" separada (Path Length/Activity aparte) —
  //   PlatformType/codFeria vienen denormalizados en cada fila.
  function classChan(ch, camp) {
    const c = String(ch || '').toLowerCase();
    const ca = String(camp || '').toLowerCase();
    if (c.includes('video') || ca.includes('video') || c.includes('youtube')) return 'Video';
    if (c.includes('search') || c.includes('paid search') || ca.includes('search')) return 'Search';
    return 'Display';
  }
  function isClick(t) {
    return String(t || '').toLowerCase().includes('click');
  }
  function parseDate(s) {
    if (s === null || s === undefined || s === '' || s === '---') return null;
    const str = String(s);
    const m = str.match(/(\d{4}[-/]\d{1,2}[-/]\d{1,2})/);
    if (m) return m[1].replace(/\//g, '-');
    return null;
  }
  function weekday(d) {
    if (!d) return null;
    const dt = new Date(d);
    return ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'][dt.getDay()];
  }
  function isB2B(act) {
    const a = String(act || '').toLowerCase();
    return a.includes('onebox') || a.includes('one_box') || a.includes('one-box');
  }

  function buildConv(steps, act, feria, pathLen, platform, daysFirst) {
    const lt = steps.find((s) => s.order === 1) || steps[steps.length - 1];
    const cats = new Set(steps.map((s) => s.cat));
    let attr;
    if (lt.cat === 'Search' && (cats.has('Video') || cats.has('Display'))) attr = 'Assisted (V/D → Search)';
    else if (lt.cat === 'Search') attr = 'Search Direct';
    else attr = 'Directly Driven (V/D)';
    const pathCats = steps.map((s) => s.cat);
    const pathSites = steps.map((s) => s.site);
    const pl = pathLen > 0 ? pathLen : steps.length;
    const astTypes = steps.slice(0, -1).map((s) => s.type);
    const astClicks = astTypes.filter((t) => isClick(t)).length;
    const astViews = astTypes.length - astClicks;
    const ltDate = parseDate(lt.date);
    const allDates = steps.map((s) => parseDate(s.date)).filter(Boolean);
    const rawChanPath = steps.map((s) => s.rawChan || s.cat);
    return {
      lt_cat: lt.cat,
      lt_site: lt.site || lt.campaign,
      lt_camp: lt.campaign,
      lt_rawChan: lt.rawChan || lt.cat,
      attr,
      feria,
      platform: platform || '',
      daysFirst: +daysFirst || 0,
      biz: isB2B(act) ? 'B2B' : 'B2C',
      pathCats,
      pathSites,
      rawChanPath,
      path: pathCats.join(' > '),
      sitePath: pathSites.join(' > '),
      rawPath: rawChanPath.join(' > '),
      pl,
      ltDate,
      allDates,
      hasSearch: cats.has('Search'),
      hasDisplay: cats.has('Display'),
      hasVideo: cats.has('Video'),
      isMulti: cats.size > 1,
      astClicks,
      astViews,
      astSites: [...new Set(pathSites.slice(0, -1))],
    };
  }

  function rowsToConvs(headers, rows) {
    const idx = {};
    headers.forEach((h, i) => (idx[h] = i));
    const need = ['ConversionId', 'InteractionNumber', 'InteractionChannel'];
    for (const n of need) {
      if (!(n in idx)) {
        throw new Error(`Columna esperada '${n}' no encontrada en la respuesta de ?action=ptc_data`);
      }
    }
    const groups = {};
    for (const row of rows) {
      const id = String(row[idx.ConversionId] ?? '');
      if (!id) continue;
      if (!groups[id]) groups[id] = { rows: [], ferias: new Set() };
      groups[id].rows.push(row);
      if (idx.codFeria !== undefined) {
        const f = String(row[idx.codFeria] ?? '').trim();
        if (f) groups[id].ferias.add(f);
      }
    }
    const convs = [];
    for (const [, grp] of Object.entries(groups)) {
      if (_ptcFeriaActive && _ptcFerias.length) {
        if (![...grp.ferias].some((f) => _ptcSelFerias.has(f))) continue;
      }
      const first = grp.rows[0];
      const platform = idx.PlatformType !== undefined ? String(first[idx.PlatformType] ?? '') : '';
      const feria = [...grp.ferias][0] || '';
      const steps = grp.rows
        .map((r) => ({
          order: Number(r[idx.InteractionNumber]),
          cat: classChan(r[idx.InteractionChannel], idx.Campaign !== undefined ? r[idx.Campaign] : ''),
          rawChan: String(r[idx.InteractionChannel] || 'Unknown'),
          campaign: idx.Campaign !== undefined ? String(r[idx.Campaign] || '') : '',
          site: idx.Site !== undefined && r[idx.Site] ? String(r[idx.Site]) : (idx.Campaign !== undefined ? String(r[idx.Campaign] || '') : ''),
          type: idx.InteractionType !== undefined ? String(r[idx.InteractionType] || '') : '',
          date: idx.InteractionDateTime !== undefined ? r[idx.InteractionDateTime] : '',
        }))
        .filter((s) => !isNaN(s.order))
        .sort((a, b) => b.order - a.order);
      if (!steps.length) continue;
      convs.push(buildConv(steps, '', feria, 0, platform, 0));
    }
    return convs;
  }

  // ── ANALYZE (idéntico al analyzer original — lógica de negocio validada) ──
  function analyze(convs) {
    const n = convs.length;
    const chanF = {};
    convs.forEach((c) => {
      if (!chanF[c.lt_cat]) chanF[c.lt_cat] = { lt: 0, ast: 0, plSum: 0, plN: 0 };
      chanF[c.lt_cat].lt++;
      chanF[c.lt_cat].plSum += c.pl;
      chanF[c.lt_cat].plN++;
    });
    convs.forEach((c) => {
      new Set(c.pathCats.slice(0, -1)).forEach((cat) => {
        if (!chanF[cat]) chanF[cat] = { lt: 0, ast: 0, plSum: 0, plN: 0 };
        chanF[cat].ast++;
      });
    });
    const siteF = {};
    convs.forEach((c) => {
      const k = c.lt_site || c.lt_camp;
      if (!siteF[k]) siteF[k] = { lt: 0, ast: 0 };
      siteF[k].lt++;
    });
    convs.forEach((c) => {
      c.astSites.forEach((s) => {
        if (!siteF[s]) siteF[s] = { lt: 0, ast: 0 };
        siteF[s].ast++;
      });
    });
    const sites = Object.entries(siteF)
      .map(([nm, d]) => ({
        nm,
        lt: d.lt,
        ast: d.ast,
        tot: d.lt + d.ast,
        astRate: +((d.ast / n) * 100).toFixed(1),
        ratio: d.lt + d.ast > 0 ? +((d.ast / (d.lt + d.ast)) * 100).toFixed(1) : 0,
      }))
      .sort((a, b) => b.tot - a.tot)
      .slice(0, 12);
    const pathC = {};
    convs.forEach((c) => {
      pathC[c.path] = (pathC[c.path] || 0) + 1;
    });
    const topPaths = Object.entries(pathC)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([raw, cnt]) => {
        const pts = raw.split(' > ');
        const u = new Set(pts);
        return { raw, cnt, pct: +((cnt / n) * 100).toFixed(1), mono: u.size === 1, chans: u };
      });
    const sitePC = {};
    convs.forEach((c) => {
      const pts = c.sitePath.split(' > ');
      const u = [...new Set(pts)];
      const key = u.length === 1 ? shorten(u[0], 22) + (pts.length > 1 ? ' ×' + pts.length : '') : shorten(pts[0], 18) + ' → ' + shorten(pts[pts.length - 1], 18) + (pts.length > 2 ? ' (+' + (pts.length - 2) + ')' : '');
      sitePC[key] = (sitePC[key] || 0) + 1;
    });
    const topSitePaths = Object.entries(sitePC)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([p, cnt]) => ({ path: p, cnt, pct: +((cnt / n) * 100).toFixed(1) }));
    const plD = { 1: 0, 2: 0, 3: 0, 4: 0, '5+': 0 };
    let plSum = 0;
    convs.forEach((c) => {
      const pl = c.pl || 1;
      plSum += pl;
      const k = pl >= 5 ? '5+' : String(pl);
      plD[k] = (plD[k] || 0) + 1;
    });
    const avgPL = (plSum / n).toFixed(1);
    const dC = convs.filter((c) => c.lt_cat === 'Display'),
      vC = convs.filter((c) => c.lt_cat === 'Video'),
      sC = convs.filter((c) => c.lt_cat === 'Search');
    const syn = {
      vAstD: dC.length ? +((dC.filter((c) => c.hasVideo).length / dC.length) * 100).toFixed(1) : 0,
      dAstV: vC.length ? +((vC.filter((c) => c.hasDisplay).length / vC.length) * 100).toFixed(1) : 0,
      dAstS: sC.length ? +((sC.filter((c) => c.hasDisplay || c.hasVideo).length / sC.length) * 100).toFixed(1) : 0,
      cross: +((convs.filter((c) => c.isMulti).length / n) * 100).toFixed(1),
    };
    let astClicks = 0,
      astViews = 0;
    convs.forEach((c) => {
      astClicks += c.astClicks;
      astViews += c.astViews;
    });
    const b2b = convs.filter((c) => c.biz === 'B2B'),
      b2c = convs.filter((c) => c.biz === 'B2C');
    const hasBB = b2b.length > 0 && b2c.length > 0 && b2b.length / n > 0.02 && b2c.length / n > 0.02;
    const b2bChanF = hasBB ? chanFunnel(b2b) : null;
    const b2cChanF = hasBB ? chanFunnel(b2c) : null;
    const convDay = {};
    convs.forEach((c) => {
      if (c.ltDate) convDay[c.ltDate] = (convDay[c.ltDate] || 0) + 1;
    });
    const wdCnts = { Lun: 0, Mar: 0, Mié: 0, Jue: 0, Vie: 0, Sáb: 0, Dom: 0 };
    convs.forEach((c) => {
      c.allDates.forEach((d) => {
        const w = weekday(d);
        if (w) wdCnts[w]++;
      });
    });
    const devCnts = {};
    convs.forEach((c) => {
      const d = c.platform || 'Desconocido';
      devCnts[d] = (devCnts[d] || 0) + 1;
    });
    const daysConvs = convs.filter((c) => c.daysFirst > 0);
    const avgDays = daysConvs.length ? +(daysConvs.reduce((s, c) => s + c.daysFirst, 0) / daysConvs.length).toFixed(1) : 0;
    const pctAst = +((convs.filter((c) => c.pl > 1).length / n) * 100).toFixed(1);
    const topDay = Object.entries(convDay).sort((a, b) => b[1] - a[1])[0];
    const rawF = {};
    convs.forEach((c) => {
      const rc = c.lt_rawChan || c.lt_cat;
      if (!rawF[rc]) rawF[rc] = { lt: 0, ast: 0 };
      rawF[rc].lt++;
    });
    convs.forEach((c) => {
      new Set((c.rawChanPath || c.pathCats).slice(0, -1)).forEach((rc) => {
        if (!rawF[rc]) rawF[rc] = { lt: 0, ast: 0 };
        rawF[rc].ast++;
      });
    });
    return { n, chanF, sites, topPaths, topSitePaths, plD, avgPL, syn, astClicks, astViews, hasBB, b2b: b2b.length, b2c: b2c.length, b2bChanF, b2cChanF, convDay, wdCnts, devCnts, avgDays, pctAst, topDay, rawF };
  }

  function chanFunnel(convs) {
    const f = {};
    convs.forEach((c) => {
      if (!f[c.lt_cat]) f[c.lt_cat] = { lt: 0, ast: 0 };
      f[c.lt_cat].lt++;
    });
    convs.forEach((c) => {
      new Set(c.pathCats.slice(0, -1)).forEach((cat) => {
        if (!f[cat]) f[cat] = { lt: 0, ast: 0 };
        f[cat].ast++;
      });
    });
    return { f };
  }

  function shorten(s, n) {
    return String(s || '').length > n ? String(s).slice(0, n) + '…' : String(s);
  }
  function fmt2(n) {
    return Number(n || 0).toLocaleString('es-ES');
  }
  function pathToPills(rawPath) {
    const pts = rawPath.split(' > ');
    const runs = [];
    let cur = pts[0],
      cnt = 1;
    for (let i = 1; i < pts.length; i++) {
      if (pts[i] === cur) cnt++;
      else {
        runs.push({ ch: cur, n: cnt });
        cur = pts[i];
        cnt = 1;
      }
    }
    runs.push({ ch: cur, n: cnt });
    return runs
      .map((r, i) => {
        const cls = r.ch === 'Search' ? 'ptc-pill-search' : r.ch === 'Video' ? 'ptc-pill-video' : 'ptc-pill-display';
        const pill = `<span class="ptc-path-tag ${cls}">${esc(r.ch)}</span>`;
        const mult = r.n > 1 ? `<span class="ptc-path-mult">×${r.n}</span>` : '';
        const arr = i < runs.length - 1 ? '<span class="ptc-path-arrow">→</span>' : '';
        return pill + mult + arr;
      })
      .join('');
  }

  function mkChart(id, type, data, opts) {
    if (_ptcCharts[id]) {
      _ptcCharts[id].destroy();
      delete _ptcCharts[id];
    }
    const ctx = document.getElementById(id);
    if (!ctx) return;
    _ptcCharts[id] = new Chart(ctx.getContext('2d'), { type, data, options: { responsive: true, maintainAspectRatio: false, ...opts } });
  }

  // ── HTML BASE DEL TAB (se inyecta una sola vez) ──
  function buildBaseHTML() {
    return `
      <div class="ptc-wrap">
        <div class="ptc-note">⚠️ El reporte Path to Conversion de CM360 es una <strong>muestra de contribución</strong>, no el total de conversiones del periodo.</div>
        <div id="ptc-feria-box" style="display:none" class="ptc-feria-box">
          <div style="font-size:12px;font-weight:700">🎪 Filtrar por feria (codFeria)</div>
          <div class="ptc-feria-chips" id="ptc-feria-chips"></div>
        </div>
        <div id="ptc-loading" class="ptc-loading">Cargando datos de Path to Conversion…</div>
        <div id="ptc-results" style="display:none">
          <div class="ptc-kpi-strip" id="ptc-kpis"></div>

          <div class="ptc-sec-lbl">01 — Atribución</div>
          <div class="ptc-sec-title">Last-Touch vs. Full-Funnel</div>
          <div class="ptc-sec-desc">Distribución del cierre de conversiones por canal y por site.</div>
          <div class="ptc-g2">
            <div class="ptc-card"><div class="ptc-card-title">Cierre por Canal</div><div style="position:relative;height:180px"><canvas id="ptc-c-chan-close"></canvas></div></div>
            <div class="ptc-card"><div class="ptc-card-title">Cierre por Site (CM360)</div><div style="position:relative;height:180px"><canvas id="ptc-c-site-close"></canvas></div></div>
          </div>

          <div class="ptc-sec-lbl">02 — Rutas de Conversión</div>
          <div class="ptc-sec-title">Top Rutas por Canal y por Site</div>
          <div class="ptc-sec-desc">Secuencias más frecuentes. Gris = ruta monomedial · Color = cruce de canales.</div>
          <div class="ptc-g2">
            <div class="ptc-card"><div class="ptc-card-title">Top 10 Rutas por Canal</div><div id="ptc-paths-chan"></div></div>
            <div class="ptc-card"><div class="ptc-card-title">Top 10 Rutas por Site</div><div id="ptc-paths-site"></div></div>
          </div>
          <div class="ptc-g2">
            <div class="ptc-card"><div class="ptc-card-title">Touchpoints antes de convertir</div><div style="position:relative;height:170px"><canvas id="ptc-c-pl"></canvas></div></div>
            <div class="ptc-card"><div class="ptc-card-title">Contribución Directa vs. Asistida</div><div style="position:relative;height:170px"><canvas id="ptc-c-chan-contrib"></canvas></div></div>
          </div>

          <div class="ptc-sec-lbl">03 — Sinergias</div>
          <div class="ptc-sec-title">Sinergias entre Canales</div>
          <div class="ptc-g2">
            <div class="ptc-card">
              <div class="ptc-card-title">Capacidad de conversión directa vs. asistida</div>
              <div class="ptc-syn-grid" id="ptc-syn-grid"></div>
              <div class="ptc-insight"><div class="ptc-ins-txt" id="ptc-syn-insight"></div></div>
            </div>
            <div class="ptc-card">
              <div class="ptc-card-title">Asistencias: Clic vs. Impresión</div>
              <div style="position:relative;height:160px"><canvas id="ptc-c-viewclick"></canvas></div>
            </div>
          </div>

          <div class="ptc-sec-lbl">04 — Sites (CM360)</div>
          <div class="ptc-sec-title">Contribución Total por Sitio</div>
          <div class="ptc-g21">
            <div class="ptc-card">
              <div class="ptc-card-title">Ranking de Sites</div>
              <div class="ptc-tbl-wrap"><table class="ptc-tbl"><thead><tr><th>Site</th><th class="ptc-nr">LT</th><th class="ptc-nr">Asist.</th><th class="ptc-nr">Total</th><th class="ptc-nr">Tasa</th></tr></thead><tbody id="ptc-site-tbody"></tbody></table></div>
            </div>
            <div class="ptc-card"><div class="ptc-card-title">Ratio de Asistencia</div><div style="position:relative;height:200px"><canvas id="ptc-c-site-ratio"></canvas></div></div>
          </div>

          <div id="ptc-bb-sec" style="display:none">
            <div class="ptc-sec-lbl">05 — Segmentación</div>
            <div class="ptc-sec-title">B2B vs. B2C</div>
            <div class="ptc-bb-grid" id="ptc-bb-grid"></div>
            <div class="ptc-g2" style="margin-top:14px">
              <div class="ptc-card"><div class="ptc-card-title">Cierre por Canal — B2B</div><div style="position:relative;height:150px"><canvas id="ptc-c-b2b-chan"></canvas></div></div>
              <div class="ptc-card"><div class="ptc-card-title">Cierre por Canal — B2C</div><div style="position:relative;height:150px"><canvas id="ptc-c-b2c-chan"></canvas></div></div>
            </div>
          </div>

          <div class="ptc-sec-lbl">06 — Temporalidad y Dispositivo</div>
          <div class="ptc-sec-title">Patrones de Comportamiento</div>
          <div class="ptc-g2">
            <div class="ptc-card"><div class="ptc-card-title">Conversiones por día</div><div style="position:relative;height:150px"><canvas id="ptc-c-day-conv"></canvas></div></div>
            <div class="ptc-card"><div class="ptc-card-title">Plataforma de conversión</div><div style="position:relative;height:150px"><canvas id="ptc-c-device"></canvas></div><div id="ptc-device-list" style="margin-top:10px"></div></div>
          </div>

          <div class="ptc-pptx-row">
            <div><div style="font-weight:700;font-size:14px">Generar presentación PPTX</div><div style="font-size:11px;color:var(--muted);margin-top:2px">Slides con análisis completo — lista para cliente</div></div>
            <button class="ptc-pptx-btn" id="ptc-pptx-btn">Descargar PPTX</button>
          </div>
        </div>
      </div>
    `;
  }

  // ── RENDER (idéntico al original, IDs con prefijo ptc-) ──
  function render(r) {
    const fE = Object.entries(r.chanF).sort((a, b) => b[1].lt - a[1].lt);
    const topC = fE[0] ? fE[0][0] : '—';
    const pl1Pct = r.plD['1'] ? +((r.plD['1'] / r.n) * 100).toFixed(1) : 0;
    const devEntries = Object.entries(r.devCnts).sort((a, b) => b[1] - a[1]);
    const topDev = devEntries[0] ? devEntries[0][0] : '—';
    const topDevPct = devEntries[0] ? +((devEntries[0][1] / r.n) * 100).toFixed(1) : 0;

    document.getElementById('ptc-kpis').innerHTML = [
      { lbl: 'Conversiones PtC', val: fmt2(r.n), sub: 'Muestra del reporte', c: 'var(--llyc-teal)' },
      { lbl: topC + ' Direct', val: (fE[0] ? (fE[0][1].lt / r.n) * 100 : 0).toFixed(1) + '%', sub: fmt2(fE[0] ? fE[0][1].lt : 0) + ' conv. last-touch', c: CHAN_COL[topC] || 'var(--llyc-teal)' },
      { lbl: (fE[1] ? fE[1][0] : '2º canal') + ' Direct', val: fE[1] ? ((fE[1][1].lt / r.n) * 100).toFixed(1) + '%' : '—', sub: fmt2(fE[1] ? fE[1][1].lt : 0) + ' conv.', c: CHAN_COL[fE[1] ? fE[1][0] : ''] || '#f9ab00' },
      { lbl: 'Días medios a conv.', val: r.avgDays > 0 ? r.avgDays : '—', sub: 'Days since first interaction', c: '#8b5cf6' },
      { lbl: 'Paths longitud 1', val: pl1Pct + '%', sub: 'Conversión en un touchpoint', c: '#1a73e8' },
      { lbl: topDev || 'Plataforma', val: topDevPct + '%', sub: topDev + ' · dispositivo LT', c: '#1e8e3e' },
    ]
      .map((k) => `<div class="ptc-kpi" style="border-left-color:${k.c}"><div class="ptc-kpi-label">${esc(k.lbl)}</div><div class="ptc-kpi-val" style="color:${k.c}">${esc(String(k.val))}</div><div class="ptc-kpi-sub">${esc(k.sub)}</div></div>`)
      .join('');

    mkChart('ptc-c-chan-close', 'doughnut', { labels: fE.map(([k]) => k), datasets: [{ data: fE.map(([, v]) => v.lt), backgroundColor: fE.map(([k]) => CHAN_COL[k] || '#94A3B8'), borderWidth: 2, borderColor: '#0d1f2d' }] }, { plugins: { legend: { position: 'bottom', labels: { font: { size: 10 }, color: '#8aaabb' } } } });

    const topSiteLT = r.sites.slice(0, 6);
    mkChart('ptc-c-site-close', 'doughnut', { labels: topSiteLT.map((s) => shorten(s.nm, 18)), datasets: [{ data: topSiteLT.map((s) => s.lt), backgroundColor: SITE_PALETTE.slice(0, topSiteLT.length), borderWidth: 2, borderColor: '#0d1f2d' }] }, { plugins: { legend: { position: 'bottom', labels: { font: { size: 9 }, color: '#8aaabb' } } } });

    const maxP = r.topPaths[0] ? r.topPaths[0].pct : 1;
    document.getElementById('ptc-paths-chan').innerHTML = r.topPaths
      .map((tp) => {
        const barCol = tp.mono ? '#5a7a8a' : tp.chans.has('Search') && tp.chans.has('Display') ? '#0098A6' : tp.chans.has('Video') ? '#ea4335' : '#8b5cf6';
        return `<div class="ptc-path-row"><span class="ptc-path-pct">${tp.pct}%</span><div class="ptc-path-channels">${pathToPills(tp.raw)}</div><div class="ptc-path-bar-wrap"><div class="ptc-path-bar" style="width:${((tp.pct / maxP) * 100).toFixed(0)}%;background:${barCol}"></div></div><span class="ptc-path-n">${fmt2(tp.cnt)}</span></div>`;
      })
      .join('');

    const maxSP = r.topSitePaths[0] ? r.topSitePaths[0].pct : 1;
    document.getElementById('ptc-paths-site').innerHTML = r.topSitePaths
      .map((tp, i) => {
        const col = SITE_PALETTE[i % SITE_PALETTE.length];
        return `<div class="ptc-path-row"><span class="ptc-path-pct">${tp.pct}%</span><span class="ptc-path-tag" style="color:${col};background:${col}22;max-width:180px;overflow:hidden;text-overflow:ellipsis">${esc(tp.path)}</span><div class="ptc-path-bar-wrap"><div class="ptc-path-bar" style="width:${((tp.pct / maxSP) * 100).toFixed(0)}%;background:${col}"></div></div><span class="ptc-path-n">${fmt2(tp.cnt)}</span></div>`;
      })
      .join('');

    const plKeys = ['1', '2', '3', '4', '5+'];
    mkChart('ptc-c-pl', 'doughnut', { labels: plKeys.map((k) => 'PL ' + k), datasets: [{ data: plKeys.map((k) => r.plD[k] || 0), backgroundColor: ['#1a73e8', '#0098A6', '#1e8e3e', '#f9ab00', '#ea4335'], borderWidth: 2, borderColor: '#0d1f2d' }] }, { plugins: { legend: { position: 'bottom', labels: { font: { size: 9 }, color: '#8aaabb' } } } });

    const chanKeys = fE.map(([k]) => k);
    mkChart('ptc-c-chan-contrib', 'bar', { labels: chanKeys, datasets: [{ label: 'Last Touch', data: chanKeys.map((k) => (r.chanF[k] || {}).lt || 0), backgroundColor: chanKeys.map((k) => CHAN_COL[k] || '#94A3B8') }, { label: 'Asistidas', data: chanKeys.map((k) => (r.chanF[k] || {}).ast || 0), backgroundColor: chanKeys.map((k) => (CHAN_COL[k] || '#94A3B8') + '80') }] }, { scales: { x: { ticks: { color: '#8aaabb' }, grid: { display: false } }, y: { ticks: { color: '#8aaabb' }, grid: { color: 'rgba(255,255,255,0.05)' } } }, plugins: { legend: { position: 'bottom', labels: { font: { size: 10 }, color: '#8aaabb' } } } });

    const topCPct = fE[0] ? ((fE[0][1].lt / r.n) * 100).toFixed(1) : 0;
    document.getElementById('ptc-syn-grid').innerHTML = [
      { pct: fE[0] ? ((fE[0][1].lt / r.n) * 100).toFixed(1) + '%' : '—', desc: `de las conversiones tienen <strong>${esc(topC)}</strong> como último touchpoint`, col: CHAN_COL[topC] || 'var(--llyc-teal)' },
      { pct: r.syn.dAstS + '%', desc: 'de conv. Search fueron precedidas por Display/Video', col: '#1e8e3e' },
      { pct: r.syn.vAstD + '%', desc: 'de conv. Display tuvieron un touchpoint de Video previo', col: '#ea4335' },
      { pct: r.syn.cross + '%', desc: 'de rutas combinan más de un canal', col: '#8b5cf6' },
    ]
      .map((s) => `<div class="ptc-syn-card"><div class="ptc-syn-pct" style="color:${s.col}">${s.pct}</div><div class="ptc-syn-desc">${s.desc}</div></div>`)
      .join('');
    document.getElementById('ptc-syn-insight').innerHTML = `<strong>Cross-canal: ${r.syn.cross}% de rutas</strong> combina más de un canal. El canal más frecuente como cierre es <strong>${esc(topC)}</strong> (${topCPct}%). Path Length medio: <strong>${r.avgPL}</strong>.`;

    const vcTotal = r.astClicks + r.astViews;
    if (vcTotal > 0) {
      mkChart('ptc-c-viewclick', 'doughnut', { labels: ['Click', 'Impresión (View)'], datasets: [{ data: [r.astClicks, r.astViews], backgroundColor: ['#1a73e8', '#f9ab00'], borderWidth: 2, borderColor: '#0d1f2d' }] }, { plugins: { legend: { position: 'bottom', labels: { font: { size: 10 }, color: '#8aaabb' } } } });
    }

    document.getElementById('ptc-site-tbody').innerHTML = r.sites
      .map((s) => `<tr><td style="font-family:'DM Mono',monospace;font-size:11px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.nm)}</td><td class="ptc-nb" style="color:#5b9bf0">${fmt2(s.lt)}</td><td class="ptc-nb" style="color:#a78bfa">${fmt2(s.ast)}</td><td class="ptc-nb">${fmt2(s.tot)}</td><td class="ptc-nb" style="color:#a78bfa">${s.astRate}%</td></tr>`)
      .join('');

    const top8 = r.sites.slice(0, 8).reverse();
    mkChart('ptc-c-site-ratio', 'bar', { labels: top8.map((s) => shorten(s.nm, 18)), datasets: [{ label: 'Ratio Asistencia %', data: top8.map((s) => s.ratio), backgroundColor: '#8b5cf680' }, { label: 'Last Touch %', data: top8.map((s) => +((s.lt / (s.lt + s.ast || 1)) * 100).toFixed(1)), backgroundColor: '#0098A640' }] }, { indexAxis: 'y', scales: { x: { max: 100, ticks: { color: '#8aaabb' }, grid: { color: 'rgba(255,255,255,0.05)' } }, y: { ticks: { color: '#8aaabb', font: { size: 9 } } } }, plugins: { legend: { position: 'bottom', labels: { font: { size: 9 }, color: '#8aaabb' } } } });

    if (r.hasBB) {
      document.getElementById('ptc-bb-sec').style.display = 'block';
      document.getElementById('ptc-bb-grid').innerHTML =
        `<div class="ptc-bb-card b2b"><div class="ptc-bb-lbl" style="color:#5b9bf0">B2B — OneBox</div><div class="ptc-bb-big" style="color:#5b9bf0">${r.b2b}</div><div style="font-size:11px;color:var(--muted)">${fmt2(r.b2b)} conversiones · ${((r.b2b / (r.n || 1)) * 100).toFixed(1)}%</div></div>` +
        `<div class="ptc-bb-card b2c"><div class="ptc-bb-lbl" style="color:#4ade80">B2C — Registros/Formularios</div><div class="ptc-bb-big" style="color:#4ade80">${r.b2c}</div><div style="font-size:11px;color:var(--muted)">${fmt2(r.b2c)} conversiones · ${((r.b2c / (r.n || 1)) * 100).toFixed(1)}%</div></div>`;
      if (r.b2bChanF) {
        const b2bE = Object.entries(r.b2bChanF.f).sort((a, b) => b[1].lt - a[1].lt);
        mkChart('ptc-c-b2b-chan', 'doughnut', { labels: b2bE.map(([k]) => k), datasets: [{ data: b2bE.map(([, v]) => v.lt), backgroundColor: b2bE.map(([k]) => CHAN_COL[k] || '#94A3B8'), borderWidth: 2, borderColor: '#0d1f2d' }] }, { plugins: { legend: { position: 'bottom', labels: { color: '#8aaabb' } } } });
        const b2cE = Object.entries(r.b2cChanF.f).sort((a, b) => b[1].lt - a[1].lt);
        mkChart('ptc-c-b2c-chan', 'doughnut', { labels: b2cE.map(([k]) => k), datasets: [{ data: b2cE.map(([, v]) => v.lt), backgroundColor: b2cE.map(([k]) => CHAN_COL[k] || '#94A3B8'), borderWidth: 2, borderColor: '#0d1f2d' }] }, { plugins: { legend: { position: 'bottom', labels: { color: '#8aaabb' } } } });
      }
    } else {
      document.getElementById('ptc-bb-sec').style.display = 'none';
    }

    const dayKeys = Object.keys(r.convDay).filter(Boolean).sort();
    if (dayKeys.length > 0) {
      mkChart('ptc-c-day-conv', 'bar', { labels: dayKeys.map((d) => d.slice(5).replace('-', '/')), datasets: [{ data: dayKeys.map((k) => r.convDay[k]), backgroundColor: '#0098A6' }] }, { scales: { x: { ticks: { color: '#8aaabb', font: { size: 9 } }, grid: { display: false } }, y: { ticks: { color: '#8aaabb' }, grid: { color: 'rgba(255,255,255,0.05)' } } }, plugins: { legend: { display: false } } });
    }

    const devE = Object.entries(r.devCnts).filter(([k]) => k && k !== '---').sort((a, b) => b[1] - a[1]).slice(0, 5);
    mkChart('ptc-c-device', 'doughnut', { labels: devE.map(([k]) => k), datasets: [{ data: devE.map(([, v]) => v), backgroundColor: ['#1a73e8', '#f9ab00', '#1e8e3e', '#ea4335', '#8b5cf6'], borderWidth: 2, borderColor: '#0d1f2d' }] }, { plugins: { legend: { display: false } } });
    document.getElementById('ptc-device-list').innerHTML = devE
      .map(([k, v], i) => `<div class="ptc-device-row"><span><span class="ptc-device-dot" style="background:${['#1a73e8', '#f9ab00', '#1e8e3e', '#ea4335', '#8b5cf6'][i]}"></span>${esc(k)}</span><strong>${((v / r.n) * 100).toFixed(1)}%</strong></div>`)
      .join('');
  }

  // ── FERIA FILTER ──
  function buildFeriaSelector(convsRaw) {
    _ptcFerias = [...new Set(convsRaw.map((c) => c.feria).filter(Boolean))].sort();
    const box = document.getElementById('ptc-feria-box');
    if (!_ptcFerias.length) {
      box.style.display = 'none';
      return;
    }
    box.style.display = 'block';
    document.getElementById('ptc-feria-chips').innerHTML = _ptcFerias
      .map((f) => `<span class="ptc-fc ${_ptcSelFerias.has(f) ? 'on' : ''}" data-feria="${esc(f)}">${esc(f)}</span>`)
      .join('');
    box.querySelectorAll('.ptc-fc').forEach((chip) => {
      chip.onclick = () => {
        const f = chip.dataset.feria;
        _ptcFeriaActive = true;
        if (_ptcSelFerias.has(f)) _ptcSelFerias.delete(f);
        else _ptcSelFerias.add(f);
        if (_ptcSelFerias.size === 0) _ptcFeriaActive = false;
        loadAndRender(true);
      };
    });
  }

  // ── PPTX EXPORT (idéntico al original) ──
  async function genPPTX() {
    if (!_ptcResult) return;
    await ensureExternalScripts();
    if (typeof PptxGenJS === 'undefined') {
      showToast('Librería PPTX no disponible');
      return;
    }
    const btn = document.getElementById('ptc-pptx-btn');
    btn.disabled = true;
    btn.textContent = 'Generando...';
    try {
      const r = _ptcResult,
        pres = new PptxGenJS(),
        n = r.n;
      pres.layout = 'LAYOUT_16x9';
      const CN = { navy: '1C2333', teal: '0098A6', tealLt: '00C4D4', blue: '1a73e8', green: '1e8e3e', yellow: 'f9ab00', red: 'ea4335', purple: '8b5cf6', white: 'FFFFFF', offW: 'F0F4F8', gray: '64748B', grayLt: 'CBD5E1' };
      const fE = Object.entries(r.chanF).sort((a, b) => b[1].lt - a[1].lt);
      const topC = fE[0] ? fE[0][0] : '—';
      const H = (s, t, sb) => {
        s.background = { color: 'F0F4F8' };
        s.addShape('rect', { x: 0.25, y: 0.18, w: 0.08, h: 0.65, fill: { color: CN.teal }, line: { color: CN.teal } });
        s.addText(t, { x: 0.45, y: 0.2, w: 9.1, h: 0.55, fontSize: 22, bold: true, color: CN.navy, fontFace: 'Calibri', margin: 0 });
        if (sb) s.addText(sb, { x: 0.45, y: 0.72, w: 9.1, h: 0.3, fontSize: 10, color: CN.gray, fontFace: 'Calibri', italic: true, margin: 0 });
      };
      const SC = (s, x, y, w, h, big, lbl, sub, col) => {
        s.addShape('rect', { x, y, w, h, fill: { color: CN.white } });
        s.addShape('rect', { x, y, w: 0.07, h, fill: { color: col }, line: { color: col } });
        s.addText(String(big), { x: x + 0.18, y: y + 0.08, w: w - 0.3, h: h * 0.52, fontSize: 24, bold: true, color: col, fontFace: 'Calibri', margin: 0, valign: 'middle' });
        s.addText(lbl, { x: x + 0.18, y: y + h * 0.6, w: w - 0.3, h: 0.28, fontSize: 10, bold: true, color: CN.navy, fontFace: 'Calibri', margin: 0 });
        if (sub) s.addText(sub, { x: x + 0.18, y: y + h * 0.6 + 0.26, w: w - 0.3, h: 0.2, fontSize: 8.5, color: CN.gray, fontFace: 'Calibri', margin: 0 });
      };

      const s1 = pres.addSlide();
      s1.background = { color: CN.navy };
      s1.addText('Path to Conversion', { x: 0.7, y: 1.0, w: 8, h: 0.7, fontSize: 36, bold: true, color: CN.white, fontFace: 'Calibri' });
      s1.addText('Insights', { x: 0.7, y: 1.65, w: 8, h: 0.6, fontSize: 32, color: CN.tealLt, fontFace: 'Calibri' });
      s1.addText('Campaign Manager 360', { x: 0.7, y: 4.5, w: 6, h: 0.35, fontSize: 13, color: CN.grayLt, fontFace: 'Calibri', italic: true });
      s1.addText(fmt2(n) + ' conversiones · muestra PtC', { x: 5.8, y: 4.85, w: 3.8, h: 0.3, fontSize: 11, color: CN.tealLt, fontFace: 'Calibri', align: 'right' });

      const s2 = pres.addSlide();
      H(s2, 'Overview — Métricas Clave', 'Las cifras PtC son muestra de contribución, no total de conversiones del periodo.');
      SC(s2, 0.35, 1.15, 2.15, 1.55, (fE[0] ? ((fE[0][1].lt / n) * 100).toFixed(1) : '-') + '%', topC + ' Direct', fmt2(fE[0] ? fE[0][1].lt : 0) + ' conv LT', CN.teal);
      SC(s2, 2.6, 1.15, 2.15, 1.55, r.pctAst + '%', 'Conversiones Asistidas', 'Con Path Length > 1', CN.purple);
      SC(s2, 4.85, 1.15, 2.15, 1.55, r.avgPL, 'Path Length Medio', 'Interacciones por conversión', CN.teal);
      SC(s2, 7.1, 1.15, 2.15, 1.55, r.avgDays > 0 ? r.avgDays + 'd' : '—', 'Días medios a conv.', '', CN.green);

      const s3 = pres.addSlide();
      H(s3, '01 — Atribución: Cierre por Canal y por Site', 'Last-Touch distribution');
      pres.addChart(pres.charts?.DOUGHNUT || 'doughnut', [{ name: 'Canal', labels: fE.map(([k]) => k), values: fE.map(([, v]) => v.lt) }], { x: 0.35, y: 1.0, w: 4.4, h: 3.7, holeSize: 55, showLegend: true, legendPos: 'b', showPercent: true, title: 'Cierre por Canal' });
      const topSiteLT = r.sites.slice(0, 6);
      pres.addChart('doughnut', [{ name: 'Site', labels: topSiteLT.map((s) => shorten(s.nm, 20)), values: topSiteLT.map((s) => s.lt) }], { x: 5.1, y: 1.0, w: 4.4, h: 3.7, holeSize: 55, showLegend: true, legendPos: 'b', showPercent: true, title: 'Cierre por Site' });

      const s4 = pres.addSlide();
      H(s4, '02 — Top Rutas de Conversión por Canal', '');
      const pathRows = [
        [{ text: 'Ruta', options: { bold: true, color: CN.white, fill: { color: CN.navy }, fontSize: 9 } }, { text: 'Conv.', options: { bold: true, color: CN.white, fill: { color: CN.navy }, align: 'center', fontSize: 9 } }, { text: '%', options: { bold: true, color: CN.white, fill: { color: CN.navy }, align: 'center', fontSize: 9 } }],
        ...r.topPaths.slice(0, 10).map((p, i) => [{ text: p.raw.length > 55 ? p.raw.slice(0, 55) + '…' : p.raw, options: { fill: { color: i % 2 === 0 ? CN.white : CN.offW }, fontSize: 9 } }, { text: fmt2(p.cnt), options: { bold: true, align: 'center', fill: { color: i % 2 === 0 ? CN.white : CN.offW }, fontSize: 9 } }, { text: p.pct + '%', options: { bold: true, align: 'center', fill: { color: i % 2 === 0 ? CN.white : CN.offW }, fontSize: 9 } }]),
      ];
      s4.addTable(pathRows, { x: 0.35, y: 1.05, w: 9.3, h: 4.3, colW: [6.8, 1.5, 1.0], border: { pt: 0.5, color: CN.grayLt }, fontFace: 'Calibri', rowH: 0.38 });

      if (r.hasBB && r.b2bChanF && r.b2cChanF) {
        const s5 = pres.addSlide();
        H(s5, '05 — B2B vs. B2C', 'OneBox = B2B · Registros/Formularios = B2C');
        SC(s5, 0.35, 1.1, 2.2, 1.4, fmt2(r.b2b), 'Conversiones B2B', 'Activity = OneBox', CN.blue);
        SC(s5, 2.7, 1.1, 2.2, 1.4, fmt2(r.b2c), 'Conversiones B2C', 'Registros · Formularios', CN.green);
      }

      await pres.writeFile({ fileName: 'Path_to_Conversion_Insights.pptx' });
      showToast('PPTX descargado ✓');
    } catch (err) {
      console.error(err);
      showToast('Error PPTX: ' + err.message);
    }
    btn.disabled = false;
    btn.textContent = 'Descargar PPTX';
  }

  // ── FETCH + PIPELINE ──
  async function loadAndRender(skipFetch) {
    const loadingEl = document.getElementById('ptc-loading');
    const resultsEl = document.getElementById('ptc-results');
    if (!skipFetch) {
      loadingEl.style.display = 'block';
      resultsEl.style.display = 'none';
      try {
        const res = await gasGet({ action: 'ptc_data' });
        if (res.error) throw new Error(res.error);
        _ptcConvs = rowsToConvs(res.headers, res.rows);
      } catch (err) {
        loadingEl.textContent = 'Error cargando datos: ' + err.message;
        console.error(err);
        return;
      }
    }
    if (!_ptcConvs.length) {
      loadingEl.style.display = 'block';
      loadingEl.textContent = 'Sin conversiones en el rango disponible.';
      resultsEl.style.display = 'none';
      return;
    }
    buildFeriaSelector(_ptcConvs);
    const filtered = _ptcFeriaActive && _ptcFerias.length ? _ptcConvs.filter((c) => _ptcSelFerias.has(c.feria)) : _ptcConvs;
    _ptcResult = analyze(filtered);
    render(_ptcResult);
    loadingEl.style.display = 'none';
    resultsEl.style.display = 'block';
  }

  // ── ENTRY POINT — llamado por dashboard-final.html al abrir el tab ──
  window.initPTCTab = async function (containerEl) {
    injectStyle();
    if (!_ptcLoaded) {
      containerEl.innerHTML = buildBaseHTML();
      document.getElementById('ptc-pptx-btn').addEventListener('click', genPPTX);
      _ptcLoaded = true;
      await ensureExternalScripts();
      await loadAndRender(false);
    }
  };
})();
