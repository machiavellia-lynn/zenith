/* ═══════════════════════════════════════════════════════════════════════
   ZENITH — ANIMATION UTILITIES
   Loaded on every page alongside tokens.css. Zero dependencies.
   ═══════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  /* ── Top progress bar ───────────────────────────────────────────────── */
  let _topBar = null;
  let _topBarTimer = null;

  function _getTopBar() {
    if (!_topBar) {
      _topBar = document.createElement('div');
      _topBar.className = 'z-topbar';
      document.body.insertBefore(_topBar, document.body.firstChild);
    }
    return _topBar;
  }

  function topbarStart() {
    if (_topBarTimer) { clearTimeout(_topBarTimer); _topBarTimer = null; }
    const b = _getTopBar();
    b.style.transition = 'none';
    b.style.width = '0%';
    b.style.opacity = '1';
    /* kick to ~80% slowly — never completes until topbarDone() */
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        b.style.transition = 'width 12s cubic-bezier(.05, 0, .15, 1)';
        b.style.width = '82%';
      });
    });
  }

  function topbarDone() {
    const b = _getTopBar();
    b.style.transition = 'width .25s ease';
    b.style.width = '100%';
    _topBarTimer = setTimeout(() => {
      b.style.transition = 'opacity .35s ease';
      b.style.opacity = '0';
      _topBarTimer = setTimeout(() => {
        b.style.transition = 'none';
        b.style.width = '0%';
        b.style.opacity = '1';
        _topBarTimer = null;
      }, 380);
    }, 260);
  }

  /* ── Easing helpers ─────────────────────────────────────────────────── */
  function _easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
  function _easeOutQuart(t) { return 1 - Math.pow(1 - t, 4); }

  /* ── Number counter animation ───────────────────────────────────────── */
  /**
   * Animate a numeric value in an element.
   * opts: { duration, from, format, decimals }
   */
  function counter(el, toValue, opts) {
    if (!el) return;
    opts = opts || {};
    const duration = opts.duration || 650;
    const from = opts.from != null ? opts.from : 0;
    const decimals = opts.decimals != null ? opts.decimals : 0;
    const format = opts.format || (v => {
      const abs = Math.abs(v);
      const sign = v < 0 ? '-' : '';
      if (abs >= 1000) return sign + (abs / 1000).toFixed(1) + 'B';
      if (abs >= 1)    return sign + abs.toFixed(1) + 'M';
      if (abs > 0)     return sign + (abs * 1000).toFixed(0) + 'K';
      return '0';
    });

    const startTime = performance.now();

    function step(now) {
      const t = Math.min((now - startTime) / duration, 1);
      const current = from + (toValue - from) * _easeOutCubic(t);
      el.textContent = format(current);
      if (t < 1) requestAnimationFrame(step);
      else el.textContent = format(toValue);
    }
    requestAnimationFrame(step);
  }

  /* ── Stats-value update flash ───────────────────────────────────────── */
  function flashVal(el) {
    if (!el) return;
    el.classList.remove('z-val-flash');
    void el.offsetWidth; /* reflow to restart animation */
    el.classList.add('z-val-flash');
    el.addEventListener('animationend', () => el.classList.remove('z-val-flash'), { once: true });
  }

  /* ── Stagger table rows ─────────────────────────────────────────────── */
  /**
   * Add a staggered fade-in to all data rows in a tbody.
   * Rows already visible won't re-animate.
   */
  function staggerRows(tbody) {
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll('tr:not(.state-row):not(.skeleton-row)'));
    rows.forEach((tr, i) => {
      const delay = Math.min(i * 14, 260);
      tr.style.animationDelay = delay + 'ms';
      tr.classList.add('z-row-in');
      tr.addEventListener('animationend', () => {
        tr.classList.remove('z-row-in');
        tr.style.animationDelay = '';
      }, { once: true });
    });
  }

  /* ── CM-bar grow animation ──────────────────────────────────────────── */
  /**
   * After tbody innerHTML is set, animate all .cm-bar widths from 0.
   */
  function cmBars(tbody) {
    if (!tbody) return;
    const bars = Array.from(tbody.querySelectorAll('.cm-bar'));
    bars.forEach(bar => {
      const target = bar.style.width;
      bar.style.transition = 'none';
      bar.style.width = '0%';
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          bar.style.transition = 'width .55s cubic-bezier(.2, 0, .2, 1)';
          bar.style.width = target;
        });
      });
    });
  }

  /* ── Modal metrics panel stagger ───────────────────────────────────── */
  /**
   * Pop-in each metric item inside a panel element.
   * Targets .mm-item and .fit-col inside panelEl.
   */
  function metricsPanel(panelEl) {
    if (!panelEl) return;
    const items = Array.from(panelEl.querySelectorAll('.mm-item, .fit-col'));
    items.forEach((item, i) => {
      item.style.animationDelay = (i * 45) + 'ms';
      item.classList.add('z-metric-pop');
      item.addEventListener('animationend', () => {
        item.classList.remove('z-metric-pop');
        item.style.animationDelay = '';
      }, { once: true });
    });
  }

  /* ── Win-rate bar ── animate from 0 to target ───────────────────────── */
  function animateWinRate(fillEl, pct) {
    if (!fillEl) return;
    fillEl.style.transition = 'none';
    fillEl.style.width = '0%';
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        fillEl.style.transition = 'width .9s cubic-bezier(.2, 0, .2, 1)';
        fillEl.style.width = (pct || 0) + '%';
      });
    });
  }

  /* ── Summary / stat cards pop ───────────────────────────────────────── */
  /**
   * Stagger-pop the summary cards (backtest sumItems, etc).
   */
  function sumValPop(containerEl) {
    if (!containerEl) return;
    const items = Array.from(containerEl.querySelectorAll('.sum-item'));
    items.forEach((item, i) => {
      item.style.animationDelay = (i * 55) + 'ms';
      item.classList.add('z-sumval-in');
      item.addEventListener('animationend', () => {
        item.classList.remove('z-sumval-in');
        item.style.animationDelay = '';
      }, { once: true });
    });
  }

  /* ── Fitness card entrance ──────────────────────────────────────────── */
  function fitnessCardIn(cardEl) {
    if (!cardEl) return;
    cardEl.classList.remove('z-card-in');
    void cardEl.offsetWidth;
    cardEl.classList.add('z-card-in');
    cardEl.addEventListener('animationend', () => cardEl.classList.remove('z-card-in'), { once: true });
  }

  /* ── Public API ─────────────────────────────────────────────────────── */
  window.ZenithAnim = {
    topbarStart,
    topbarDone,
    counter,
    flashVal,
    staggerRows,
    cmBars,
    metricsPanel,
    animateWinRate,
    sumValPop,
    fitnessCardIn,
  };

})();
