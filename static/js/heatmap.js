/* Contribution heat-map renderer.
   Heat.render(el, { data, cfg, weeks?, year?, first?, cell?, gap?, labels? })
   data: { "YYYY-MM-DD": value }   cfg: { color, mode: 'gradient'|'levels', target, levels[], unit, metric } */
const Heat = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const DAY = 86400000;
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const DOW = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const parse = s => { const [y,m,d] = s.split('-').map(Number); return new Date(y, m-1, d); };
  const mondayOf = d => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate()); x.setDate(x.getDate() - ((x.getDay()+6) % 7)); return x; };
  const addDays = (d, n) => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate()); x.setDate(x.getDate()+n); return x; };
  const num = v => { v = Math.round(v*100)/100; return Number.isInteger(v) ? String(v) : String(v); };

  function dur(m) {
    m = Math.round(m);
    if (m < 60) return `${m} min`;
    return m % 60 === 0 ? `${m/60} h` : `${Math.floor(m/60)} h ${String(m%60).padStart(2,'0')} m`;
  }
  function fmt(v, cfg) {
    if (cfg.metric === 'delay') {
      v = Math.round(v);
      return v === 0 ? 'On time' : `${dur(Math.abs(v))} ${v > 0 ? 'late' : 'early'}`;
    }
    const u = (cfg.unit || '').trim(), lu = u.toLowerCase();
    if (u === 'habits') return `${num(v)} habit${v === 1 ? '' : 's'}`;
    if (lu.startsWith('min')) return dur(v);
    if (lu === 'h' || lu === 'hr' || lu === 'hrs' || lu.startsWith('hour')) return `${num(v)} h`;
    if ((lu === 'pages' || lu === 'page') && v === 1) return '1 page';
    return `${num(v)} ${u}`.trim();
  }

  /* How strongly (0-100 % of the habit colour) a value is painted. null = unlogged / on-time ring */
  function strength(v, cfg) {
    const eff = cfg.metric === 'delay' ? Math.max(0, v) : v;
    if (!(eff > 0)) return 0;
    if (cfg.mode === 'levels' && cfg.levels && cfg.levels.length) {
      const n = cfg.levels.length;
      const lvl = Math.max(1, cfg.levels.filter(l => l <= eff).length);
      return n === 1 ? 100 : 28 + 72 * (lvl - 1) / (n - 1);
    }
    const t = Math.min(1, eff / (cfg.target > 0 ? cfg.target : 1));
    return 22 + 78 * t;
  }
  const paint = (pct, cfg) => `color-mix(in oklab, ${cfg.color} ${pct.toFixed(1)}%, var(--cell))`;

  function el(name, attrs, parent) {
    const n = document.createElementNS(NS, name);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function render(host, o) {
    const cfg = o.cfg, data = o.data || {};
    const cell = o.cell || 11, gap = o.gap || 3, step = cell + gap;
    const labels = o.labels !== false;
    const today = new Date(); today.setHours(0,0,0,0);

    let start, end;
    if (o.year) { start = mondayOf(new Date(o.year, 0, 1)); end = new Date(o.year, 11, 31); }
    else {
      let weeks = o.weeks || 53;
      if (weeks === 'auto') {
        const first = parse(o.first || iso(today));
        weeks = Math.min(53, Math.max(o.minWeeks || 20, Math.ceil((today - first) / DAY / 7) + 2));
      }
      end = today; start = addDays(mondayOf(today), -7 * (weeks - 1));
    }
    const cols = Math.round((mondayOf(end) - start) / DAY / 7) + 1;
    const left = labels ? 30 : 0, top = labels ? 16 : 0;
    const W = left + cols * step - gap, H = top + 7 * step - gap;

    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', role: 'img',
                            'aria-label': 'Activity heat-map', class: 'heat-svg' });
    svg.style.maxWidth = (W * (o.maxScale || 2)) + 'px';
    if (o.minWidth) svg.style.minWidth = o.minWidth + 'px';

    if (labels) {
      [0, 2, 4].forEach(r => { const t = el('text', { x: 0, y: top + r*step + cell - 1, class: 'heat-label' }, svg); t.textContent = DOW[r]; });
    }
    let lastMonth = -1;
    for (let c = 0; c < cols; c++) {
      const monday = addDays(start, c * 7);
      if (labels) {
        const first = addDays(monday, 0);
        // label a column when the month changes within it (and there is room)
        for (let r = 0; r < 7; r++) {
          const d = addDays(monday, r);
          if (d.getDate() === 1 && d.getMonth() !== lastMonth && d >= start) {
            const t = el('text', { x: left + c*step, y: 10, class: 'heat-label' }, svg); t.textContent = MONTHS[d.getMonth()];
            lastMonth = d.getMonth(); break;
          }
        }
      }
      for (let r = 0; r < 7; r++) {
        const d = addDays(monday, r);
        if (d > end || d < start || (o.year && d.getFullYear() !== o.year)) continue;
        const k = iso(d), v = data[k];
        const rect = el('rect', { x: left + c*step, y: top + r*step, width: cell, height: cell, rx: Math.max(2, cell*0.22), class: 'heat-cell' }, svg);
        rect.dataset.d = k;
        if (v !== undefined && v !== null) {
          rect.dataset.v = v;
          const pct = strength(v, cfg);
          if (pct > 0) rect.style.fill = paint(pct, cfg);
          else rect.classList.add('ring');
        }
        if (k === iso(today)) rect.classList.add('today');
      }
    }
    host.replaceChildren(svg);
    host._heat = o;
  }

  function legend(host, cfg) {
    const steps = (cfg.mode === 'levels' && cfg.levels && cfg.levels.length)
      ? [0, ...cfg.levels.map((_, i, a) => a.length === 1 ? 100 : 28 + 72 * i / (a.length - 1))]
      : [0, 22, 40, 58, 76, 100];
    host.innerHTML = '';
    const less = document.createElement('span'); less.textContent = 'Less'; host.appendChild(less);
    steps.forEach(p => { const s = document.createElement('i'); s.className = 'sw'; if (p) s.style.background = paint(p, cfg); host.appendChild(s); });
    const more = document.createElement('span'); more.textContent = 'More'; host.appendChild(more);
  }

  /* shared tooltip */
  let tip;
  function wireTooltip() {
    tip = document.createElement('div'); tip.className = 'heat-tip'; tip.hidden = true; document.body.appendChild(tip);
    const show = (e) => {
      const r = e.target.closest && e.target.closest('rect.heat-cell');
      const host = r && r.closest('[data-heat-host]');
      if (!r || !host || !host._heat) { tip.hidden = true; return; }
      const cfg = host._heat.cfg, d = parse(r.dataset.d);
      const label = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
      tip.innerHTML = '';
      const a = document.createElement('b'); a.textContent = r.dataset.v !== undefined ? fmt(parseFloat(r.dataset.v), cfg) : 'Nothing logged';
      const b = document.createElement('span'); b.textContent = label;
      tip.append(a, b);
      tip.hidden = false;
      const box = r.getBoundingClientRect(), tb = tip.getBoundingClientRect();
      tip.style.left = Math.max(8, Math.min(innerWidth - tb.width - 8, box.left + box.width/2 - tb.width/2)) + 'px';
      tip.style.top = (box.top - tb.height - 8 + scrollY) + 'px';
    };
    document.addEventListener('pointerover', show);
    document.addEventListener('pointerdown', show);
    document.addEventListener('scroll', () => tip.hidden = true, { passive: true });
  }
  document.addEventListener('DOMContentLoaded', wireTooltip);

  return { render, legend, fmt, iso, strength, paint };
})();
