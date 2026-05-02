# ZENITH UI REDESIGN PROMPT

## Context

I have a dark-theme trading dashboard called **Zenith** with 5 HTML pages: `flow.html`, `chart.html`, `admin.html`, `hub.html`, and `backtest.html`. All pages share the same design system. I want you to apply a set of UI/UX improvements to each page. The attached files contain the current code.

**Critical constraint: do NOT change any colors, fonts, or CSS variables.** The identity stays exactly the same:
- Colors: `--bg: #080c10`, `--surface: #0e1318`, `--surface2: #121920`, `--border: #1a2230`, `--border2: #243040`, `--accent: #00e8a2`, `--accent2: #4d9fff`, `--danger: #ff4d6a`
- Fonts: Space Mono (labels, values, nav) + DM Sans (body text)
- Dark terminal aesthetic stays intact

Only modify CSS and HTML structure as described below. Do not touch any JavaScript logic.

---

## GLOBAL CHANGES (apply to all 5 pages)

### 1. Header / Navigation

**Current:** Nav buttons are flat individual buttons in a row with no grouping. Logo has no visual emphasis. IHSG sits inline.

**New:**
- Wrap all nav buttons (`<a class="nav-btn">`) inside a single group container:
  ```html
  <div class="nav-group">
    <a href="..." class="nav-btn ...">...</a>
    ...
  </div>
  ```
- Add `.nav-group` CSS:
  ```css
  .nav-group {
    display: flex;
    align-items: center;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px;
    gap: 2px;
  }
  ```
- Update `.nav-btn` — remove individual border, make it borderless by default, only show accent border when active:
  ```css
  .nav-btn {
    background: none;
    border: 1px solid transparent;
    color: var(--muted);
    border-radius: 4px;
    padding: 4px 12px;
    cursor: pointer;
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    letter-spacing: .06em;
    text-decoration: none;
    transition: all .15s;
  }
  .nav-btn:hover { color: var(--accent); }
  .nav-btn.active {
    background: var(--surface);
    border-color: rgba(0,232,162,.25);
    color: var(--accent);
  }
  ```
- Add a glowing dot to the logo markup:
  ```html
  <a href="/" class="logo"><span class="logo-dot"></span>ZENITH<span class="logo-sub"> / pagename</span></a>
  ```
  ```css
  .logo-dot {
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 8px var(--accent);
    margin-right: 7px;
    flex-shrink: 0;
  }
  ```
- Add a top-edge gradient line to the header:
  ```css
  header {
    position: relative;
    /* keep existing styles, add: */
  }
  header::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0,232,162,.3), transparent);
  }
  ```
- Where IHSG exists in header, stack it vertically:
  ```html
  <div class="ihsg-wrap">
    <span class="ihsg-label">IHSG</span>
    <span class="ihsg-price" id="ihsgPrice">—</span>
    <span class="ihsg-gain" id="ihsgGain">—</span>
  </div>
  ```
  ```css
  .ihsg-wrap {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 1px;
    font-family: 'Space Mono', monospace;
  }
  .ihsg-label { font-size: 8px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
  .ihsg-price { font-size: 13px; font-weight: 700; color: var(--text); }
  .ihsg-gain  { font-size: 9px; font-weight: 700; }
  ```

### 2. Buttons

**Primary button** — add a subtle bottom highlight:
```css
.btn {
  /* keep existing styles, add: */
  position: relative;
  overflow: hidden;
}
.btn::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 1px;
  background: rgba(255,255,255,.25);
}
```

**Outline/ghost button** — update border color to `border2` for more visibility:
```css
.btn.outline {
  border-color: var(--border2);
}
.btn.outline:hover {
  border-color: rgba(0,232,162,.35);
  color: var(--accent);
  background: rgba(0,232,162,.04);
}
```

**Add a danger-ghost variant:**
```css
.btn.danger {
  background: rgba(255,77,106,.08);
  border: 1px solid rgba(255,77,106,.25);
  color: var(--danger);
}
.btn.danger:hover { background: rgba(255,77,106,.15); }
```

### 3. Input Fields

Increase border visibility and padding slightly:
```css
input[type="text"], input[type="number"], .date-input, .num-input {
  border-color: var(--border2);   /* was --border */
  padding: 8px 12px;              /* slightly more padding */
  transition: border-color .15s;
}
input:focus, .date-input:focus, .num-input:focus {
  border-color: var(--accent);
}
```

### 4. Badges / Phase Labels

Make all phase/action/status badges pill-shaped:
```css
.phase-badge, [class*="phase-badge"] {
  border-radius: 20px;
  border: 1px solid transparent;
  padding: 3px 10px;
}
.phase-badge.spring  { background: rgba(0,232,162,.1);  color: #00e8a2; border-color: rgba(0,232,162,.2); }
.phase-badge.absorb  { background: rgba(77,159,255,.1); color: #4d9fff; border-color: rgba(77,159,255,.2); }
.phase-badge.sos     { background: rgba(0,232,162,.15); color: #00e8a2; border-color: rgba(0,232,162,.25); }
.phase-badge.upthrust{ background: rgba(255,140,66,.1);  color: #ff8c42; border-color: rgba(255,140,66,.2); }
.phase-badge.distri  { background: rgba(255,77,106,.08); color: #ff4d6a; border-color: rgba(255,77,106,.18); }
.phase-badge.accum   { background: rgba(0,232,162,.08); color: #5abf8e; border-color: rgba(90,191,142,.18); }
.phase-badge.neutral { background: rgba(74,96,112,.12); color: var(--muted); border-color: rgba(74,96,112,.2); }
```

---

## PAGE-SPECIFIC CHANGES

---

### `flow.html`

#### Stats Bar
Restructure the `.stats-bar` from inline items to a column-based layout with vertical dividers. Move NET CM first as the primary metric:

```html
<div class="stats-bar" id="statsBar">
  <div class="stat-item highlight" title="Net Clean Money">
    <span class="s-label">NET CM</span>
    <span class="s-val" id="sNCM">—</span>
  </div>
  <div class="stat-item" title="Smart Money">
    <span class="s-label">SM</span>
    <span class="s-val neutral" id="sSM">—</span>
  </div>
  <div class="stat-item" title="Bad Money">
    <span class="s-label">BM</span>
    <span class="s-val bm" id="sBM">—</span>
  </div>
  <div class="stat-item" title="Money Inflow">
    <span class="s-label">MF+</span>
    <span class="s-val up" id="sMFP">—</span>
  </div>
  <div class="stat-item" title="Money Outflow">
    <span class="s-label">MF−</span>
    <span class="s-val down" id="sMFM">—</span>
  </div>
  <div class="stat-item" title="Net Money Flow">
    <span class="s-label">NET MF</span>
    <span class="s-val" id="sNMF">—</span>
  </div>
  <div class="stat-item">
    <span class="s-label">Tickers</span>
    <span class="s-val neutral" id="sCount">—</span>
  </div>
  <div class="stat-item stat-ihsg" title="IHSG Composite">
    <span class="s-label">IHSG</span>
    <span class="s-val" id="sIHSG" style="color:var(--text)">—</span>
  </div>
</div>
```

Update `.stats-bar` CSS:
```css
.stats-bar {
  display: flex;
  align-items: stretch;
  background: var(--surface);
  border-bottom: 1px solid var(--border2);
  overflow-x: auto;
}
.stat-item {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 3px;
  padding: 10px 18px;
  border-right: 1px solid var(--border);
  white-space: nowrap;
  min-width: 80px;
  flex-shrink: 0;
}
.stat-item.stat-ihsg {
  margin-left: auto;
  border-right: none;
  border-left: 1px solid var(--border);
}
.stat-item.highlight {
  background: rgba(0,232,162,.025);
}
.s-label {
  font-family: 'Space Mono', monospace;
  font-size: 8px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--muted);
}
.s-val {
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}
```

#### Toolbar
Wrap the two date inputs into a single group container:
```html
<div class="toolbar">
  <!-- sector back/badge (keep existing) -->
  <div class="date-group">
    <input type="text" class="date-input" id="dateFrom" placeholder="DD/MM/YYYY" maxlength="10"/>
    <div class="date-arrow" id="dateModeToggle" onclick="toggleDateMode()">→</div>
    <input type="text" class="date-input" id="dateTo" placeholder="DD/MM/YYYY" maxlength="10"/>
  </div>
  <!-- filter dropdown, row count (keep existing) -->
</div>
```
```css
.date-group {
  display: flex;
  align-items: center;
  background: var(--bg);
  border: 1px solid var(--border2);
  border-radius: 6px;
  overflow: hidden;
}
.date-group .date-input {
  border: none;
  border-right: 1px solid var(--border);
  border-radius: 0;
  background: transparent;
  padding: 7px 10px;
}
.date-group .date-input:last-child { border-right: none; }
.date-group .date-arrow {
  color: var(--muted);
  font-size: 11px;
  padding: 0 8px;
  background: none;
  border: none;
  cursor: pointer;
}
```

Add active indicator to the filter button — when filters are active, show a small dot:
```css
.filter-btn {
  position: relative;
}
/* JS: add class 'has-filter' to .filter-btn when any checkbox is unchecked */
.filter-btn.has-filter::before {
  content: '';
  position: absolute;
  top: 4px; right: 4px;
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--accent);
}
```

#### Table
Update table header styles for better contrast:
```css
#flowTable thead th {
  background: var(--bg);           /* darker than current surface2 */
  border-bottom: 2px solid var(--border2);
  padding: 10px 10px;
}
#flowTable thead th.sorted {
  color: var(--accent);
}
#flowTable tbody tr:hover {
  background: rgba(0,232,162,.025);  /* subtle tinted hover */
}
```

#### Ticker Row (table body)
Add a colored left-border to each row based on action signal. Do this in JavaScript when rendering rows — add a style to the `<tr>`:
- BUY signal → `border-left: 2px solid var(--up)`
- SELL signal → `border-left: 2px solid var(--down)`
- HOLD → `border-left: 2px solid var(--border2)`

---

### `chart.html`

#### Timeframe Buttons
Wrap `.tf-btn` buttons into a group container similar to nav-group:
```html
<div class="tf-group">
  <button class="tf-btn" ...>5m</button>
  <button class="tf-btn active" ...>1D</button>
  ...
</div>
```
```css
.tf-group {
  display: flex;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 3px;
  gap: 2px;
}
.tf-btn {
  background: none;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--muted);
  padding: 4px 12px;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  cursor: pointer;
  transition: all .15s;
  letter-spacing: .06em;
}
.tf-btn:hover { color: var(--accent); }
.tf-btn.active {
  background: var(--surface);
  border-color: rgba(0,232,162,.25);
  color: var(--accent);
}
```

#### Metrics Panel
Add a header to the metrics panel and move PHASE + ACTION there as primary signal. Find the `#metricsPanel` div and restructure:

```html
<div class="metrics-panel" id="metricsPanel">
  <div class="mp-header">
    <span class="mp-title">Metrics</span>
    <span class="mp-phase-badge" id="mpPhaseBadge">— · —</span>
  </div>
  <div class="mp-grid">
    <div class="mp-item"><div class="mp-label">Avg SM</div><div id="mpAvgSM" class="mp-val" style="color:var(--accent2)">—</div></div>
    <div class="mp-item"><div class="mp-label">Avg BM</div><div id="mpAvgBM" class="mp-val" style="color:#ff8c42">—</div></div>
    <div class="mp-item"><div class="mp-label">ATR%</div><div id="mpATR" class="mp-val">—</div></div>
    <div class="mp-item"><div class="mp-label">SRI</div><div id="mpSRI" class="mp-val">—</div></div>
    <div class="mp-item"><div class="mp-label">MES</div><div id="mpMES" class="mp-val">—</div></div>
    <div class="mp-item"><div class="mp-label">RPR</div><div id="mpRPR" class="mp-val">—</div></div>
    <div class="mp-item"><div class="mp-label">Vx Gap</div><div id="mpVXG" class="mp-val">—</div></div>
  </div>
</div>
```

Note: `mpPhase` and `mpAction` are now combined into `mpPhaseBadge` — update the JS that sets these values to use: `document.getElementById('mpPhaseBadge').textContent = phase + ' · ' + action`. Keep the original `mpPhase` and `mpAction` element IDs as hidden fallbacks if needed.

```css
.metrics-panel {
  background: var(--surface);
  border: 1px solid var(--border2);
  border-radius: 10px;
  overflow: hidden;
  padding: 0;   /* remove existing padding */
}
.mp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface2);
}
.mp-title {
  font-family: 'Space Mono', monospace;
  font-size: 9px;
  letter-spacing: .12em;
  color: var(--muted);
  text-transform: uppercase;
}
.mp-phase-badge {
  font-family: 'Space Mono', monospace;
  font-size: 9px;
  padding: 3px 10px;
  border-radius: 20px;
  background: rgba(0,232,162,.1);
  color: var(--accent);
  border: 1px solid rgba(0,232,162,.2);
}
.mp-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 1px;
  background: var(--border);
}
.mp-item {
  background: var(--surface);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.mp-label {
  font-family: 'Space Mono', monospace;
  font-size: 8px;
  color: var(--muted);
  letter-spacing: .1em;
  text-transform: uppercase;
}
.mp-val {
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}
```

---

### `admin.html`

#### Cards
Add a proper header section to each `.card` that separates the title from the form content:

For each card, wrap the `.card-title` + `.card-sub` in a header div:
```html
<div class="card">
  <div class="card-header">
    <div class="card-title">Database</div>
    <div class="card-sub">zenith.db</div>
  </div>
  <div class="card-body">
    <!-- existing .card-row content -->
  </div>
</div>
```

```css
.card {
  padding: 0;  /* remove existing padding */
}
.card-header {
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--surface2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.card-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card-title {
  /* keep existing but remove margin adjustments */
}
```

#### Stat Grid
Update `.stat-box` to have a visible left-accent based on stat type:
```css
.stat-box {
  border-left: 2px solid var(--border2);  /* default */
}
/* In HTML, add data attributes or classes to distinguish: */
.stat-box.up   { border-left-color: var(--up); }
.stat-box.down { border-left-color: var(--down); }
.stat-box.sm   { border-left-color: var(--accent2); }
.stat-box.bm   { border-left-color: #ff8c42; }
```
Update the stat boxes for SM/BM/MF+/MF- in HTML to add the matching class, e.g.:
```html
<div class="stat-box sm"><div class="stat-label">Latest SM</div><div class="stat-val sm" id="stSM">—</div></div>
<div class="stat-box bm"><div class="stat-label">Latest BM</div><div class="stat-val bm" id="stBM">—</div></div>
<div class="stat-box up"><div class="stat-label">Latest MF+</div><div class="stat-val up" id="stMFP">—</div></div>
<div class="stat-box down"><div class="stat-label">Latest MF-</div><div class="stat-val down" id="stMFM">—</div></div>
```

---

### `hub.html`

#### Hero Section
Replace the current hero with this improved structure:
```html
<div class="hero">
  <div class="hero-eyebrow">Smart Money Analysis</div>
  <div class="hero-logo">ZENITH</div>
  <div class="hero-tag">IDX Market Intelligence Platform</div>
</div>

<div class="stats-row">
  <div class="stats-row-inner">
    <div class="sr-item"><span class="sr-label">IHSG</span><span class="sr-val" id="sIHSG" style="color:var(--text)">—</span></div>
    <div class="sr-sep"></div>
    <div class="sr-item"><span class="sr-label">WIB</span><span class="sr-val" id="sTime" style="color:var(--text)">—</span></div>
    <div class="sr-sep"></div>
    <div class="sr-item"><span class="sr-label">Total SM</span><span class="sr-val" id="sSM" style="color:var(--accent2)">—</span></div>
  </div>
</div>
```

```css
.hero {
  text-align: center;
  padding: 44px 24px 8px;
  position: relative;
}
.hero::before {
  content: '';
  position: absolute;
  top: 0; left: 50%; transform: translateX(-50%);
  width: 280px; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(0,232,162,.4), transparent);
}
.hero-eyebrow {
  font-family: 'Space Mono', monospace;
  font-size: 9px;
  letter-spacing: .22em;
  color: var(--muted);
  text-transform: uppercase;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.hero-eyebrow::before, .hero-eyebrow::after {
  content: '';
  width: 24px;
  height: 1px;
  background: var(--border2);
}
.hero-logo {
  font-family: 'Space Mono', monospace;
  font-size: 36px;
  font-weight: 700;
  letter-spacing: .35em;
  color: var(--accent);
  line-height: 1;
}
.hero-tag {
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: .18em;
  color: var(--muted);
  text-transform: uppercase;
  margin-top: 10px;
}
.stats-row {
  display: flex;
  justify-content: center;
  padding: 20px 24px;
}
.stats-row-inner {
  display: flex;
  align-items: stretch;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.sr-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 24px;
  align-items: center;
}
.sr-sep {
  width: 1px;
  background: var(--border);
  align-self: stretch;
}
.sr-label {
  font-family: 'Space Mono', monospace;
  font-size: 8px;
  color: var(--muted);
  letter-spacing: .12em;
  text-transform: uppercase;
}
.sr-val {
  font-family: 'Space Mono', monospace;
  font-size: 14px;
  font-weight: 700;
}
```

#### Navigation Cards
Redesign the cards — remove emoji icons, add a top accent bar, and add a footer arrow:

```html
<div class="cards">
  <a href="/chart" class="card">
    <div class="card-accent-bar"></div>
    <div class="card-title">Chart</div>
    <div class="card-sub">End-of-Day Candlestick IDX</div>
    <div class="card-desc">Analisis pergerakan harga saham IDX dengan timeframe 5m hingga 1D. Dilengkapi overlay CM, SM, dan BM langsung di atas candlestick.</div>
    <div class="card-footer"><span class="card-arrow">→</span></div>
  </a>
  <a href="/flow" class="card primary">
    <div class="card-accent-bar"></div>
    <div class="card-title">Flow</div>
    <div class="card-sub">Smart & Bad Money Flow</div>
    <div class="card-desc">Pantau aliran dana smart money dan bad money per emiten IDX. Filter tanggal, multi-sort, dan detail transaksi lengkap per ticker.</div>
    <div class="card-footer"><span class="card-arrow">→</span></div>
  </a>
  <a href="/sector" class="card">
    <div class="card-accent-bar"></div>
    <div class="card-title">Sector</div>
    <div class="card-sub">Sector Rotation Analysis</div>
    <div class="card-desc">Identifikasi sektor yang sedang diakumulasi atau didistribusi. Breakdown CM, SM, BM per sektor industri IDX.</div>
    <div class="card-footer"><span class="card-arrow">→</span></div>
  </a>
  <a href="/backtest" class="card">
    <div class="card-accent-bar"></div>
    <div class="card-title">Backtest</div>
    <div class="card-sub">Strategy Leaderboard</div>
    <div class="card-desc">Uji performa kombinasi entry dan exit signal terhadap data historis IDX.</div>
    <div class="card-footer"><span class="card-arrow">→</span></div>
  </a>
</div>
```

```css
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-top: 2px solid var(--border2);  /* default top border */
  border-radius: 10px;
  padding: 20px;
  cursor: pointer;
  transition: border-color .2s, transform .15s;
  display: flex;
  flex-direction: column;
  gap: 10px;
  text-decoration: none;
  color: var(--text);
  position: relative;
  overflow: hidden;
}
.card::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 1px;
  background: transparent;
  transition: background .2s;
}
.card:hover {
  border-color: var(--border2);
  transform: translateY(-2px);
}
.card:hover::after {
  background: linear-gradient(90deg, transparent, rgba(0,232,162,.2), transparent);
}
.card.primary {
  border-top-color: var(--accent);
}
.card.primary::after {
  background: linear-gradient(90deg, transparent, rgba(0,232,162,.12), transparent);
}
.card-accent-bar {
  width: 28px;
  height: 3px;
  border-radius: 2px;
  background: var(--border2);
  margin-bottom: 2px;
}
.card.primary .card-accent-bar {
  background: var(--accent);
}
.card-title {
  font-family: 'Space Mono', monospace;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--text);
}
.card-sub {
  font-size: 10px;
  font-family: 'Space Mono', monospace;
  color: var(--accent);
  letter-spacing: .04em;
  margin-top: -4px;
}
.card-desc {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.55;
  flex: 1;
}
.card-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}
.card-arrow {
  font-family: 'Space Mono', monospace;
  font-size: 14px;
  color: var(--border2);
  transition: color .15s;
}
.card:hover .card-arrow { color: var(--accent); }
```

---

### `backtest.html`

#### Summary Cards
Update `.sum-item` for better visual weight:
```css
.sum-item {
  background: var(--surface);
  border: 1px solid var(--border2);
  border-radius: 8px;
  padding: 12px 18px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 120px;
}
.sum-label {
  font-family: 'Space Mono', monospace;
  font-size: 8px;
  letter-spacing: .1em;
  color: var(--muted);
  text-transform: uppercase;
}
.sum-val {
  font-family: 'Space Mono', monospace;
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
}
```

#### Table Header
Apply the same table header treatment as flow.html:
```css
table thead th {
  background: var(--bg);
  border-bottom: 2px solid var(--border2);
}
table thead th.sorted { color: var(--accent); }
tbody tr:hover { background: rgba(0,232,162,.025); }
```

#### Trade Detail Modal
Update modal header for the drill-down modal:
```css
.modal-header {
  border-bottom: 1px solid var(--border);
  position: relative;
  background: var(--surface2);
}
.modal-header::after {
  content: '';
  position: absolute;
  bottom: 0; left: 20px;
  width: 40px; height: 2px;
  background: var(--accent);
  border-radius: 1px 1px 0 0;
}
.modal-title {
  font-family: 'Space Mono', monospace;
  font-size: 13px;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: .06em;
}
```

---

## FINAL NOTES FOR CLAUDE

- Preserve **all existing JavaScript** exactly as-is. Only modify HTML structure and CSS.
- When restructuring HTML (e.g., wrapping elements), make sure IDs used by JS (`id="statsBar"`, `id="flowBody"`, `id="mpPhase"`, etc.) are preserved on the correct elements.
- For `mpPhase` and `mpAction` in chart.html: keep them as hidden `<span>` elements (with `display:none`) so existing JS that sets them still works, but surface the combined value in `mpPhaseBadge`.
- Apply responsive overrides (`@media (max-width: 768px)`) carefully — only adjust where the new layout breaks on mobile.
- Process one file at a time and output the complete updated file.
