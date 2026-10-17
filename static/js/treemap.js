// Today's logged amounts as a treemap, grouped by unit (uses the habit's own colour).
if (window.d3) fetch('/api/habits/today' + (document.getElementById('treemaps-container').dataset.category ? '?category=' + document.getElementById('treemaps-container').dataset.category : ''))
  .then(r => r.json())
  .then(grouped => {
    const container = document.getElementById('treemaps-container');
    const entries = Object.entries(grouped);
    if (!entries.length) return;
    document.getElementById('today-block').hidden = false;
    const width = container.clientWidth || 900;

    entries.forEach(([unit, items]) => {
      const section = document.createElement('div');
      section.style.marginTop = '22px';
      const title = document.createElement('h3');
      title.textContent = unit;
      const map = document.createElement('div');
      map.className = 'treemap';
      const height = Math.max(120, Math.min(300, 70 + items.length * 40));
      map.style.height = height + 'px';
      section.append(title, map);
      container.appendChild(section);

      const root = d3.hierarchy({ children: items }).sum(d => d.value);
      d3.treemap().size([width, height]).padding(3)(root);
      root.leaves().forEach(d => {
        const t = document.createElement('div');
        t.className = 'tm-tile';
        t.style.cssText = `left:${d.x0}px;top:${d.y0}px;width:${d.x1 - d.x0}px;height:${d.y1 - d.y0}px;--c:${d.data.color}`;
        const name = document.createElement('span'); name.textContent = d.data.name;
        const small = document.createElement('small'); small.textContent = d.data.label + (d.data.goal ? ' of ' + d.data.goal : '');
        t.append(name, small);
        map.appendChild(t);
      });
    });
  });
