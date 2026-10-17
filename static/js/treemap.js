// static/js/treemap.js
fetch('/api/habits/today')
  .then(r => r.json())
  .then(grouped => {
    const container = document.getElementById('treemaps-container');
    const width = container.clientWidth || 1000;
    const height = 400;

    function progressColor(value, goal) {
      if (!goal || goal <= 0) return '#9ca3af';  // gray if no goal set
      const ratio = value / goal;
      if (ratio >= 1) return '#22c55e';   // green — goal hit
      if (ratio >= 0.5) return '#f59e0b'; // amber — halfway there
      return '#ef4444';                    // red — far off
    }

    Object.entries(grouped).forEach(([unit, items]) => {
      const section = document.createElement('div');
      section.style.marginBottom = '2rem';
      section.innerHTML = `<h3>${unit}</h3><div class="treemap" style="position:relative; width:${width}px; height:${height}px;"></div>`;
      container.appendChild(section);

      const root = d3.hierarchy({children: items}).sum(d => d.value);
      d3.treemap().size([width, height]).padding(2)(root);

      d3.select(section.querySelector('.treemap'))
        .selectAll('div')
        .data(root.leaves())
        .join('div')
        .style('position', 'absolute')
        .style('left', d => d.x0 + 'px')
        .style('top', d => d.y0 + 'px')
        .style('width', d => (d.x1 - d.x0) + 'px')
        .style('height', d => (d.y1 - d.y0) + 'px')
        .style('background', d => progressColor(d.data.value, d.data.goal))
        .style('display', 'flex')
        .style('align-items', 'center')
        .style('justify-content', 'center')
        .style('color', 'white')
        .style('font-size', '15px')
        .style('font-weight', '500')
        .style('text-align', 'center')
        .style('padding', '4px')
        .style('box-sizing', 'border-box')
        .text(d => `${d.data.name} (${d.data.value}/${d.data.goal})`);
    });
  });