/* ═══════════════════════════════════════════════════════════════════════
   ZENITH — GLOBAL KEYBOARD SHORTCUTS + CLEAR BUTTONS + ESC HANDLING
   Loaded on every page. Zero dependencies.
   ═══════════════════════════════════════════════════════════════════════ */

(function(){
  'use strict';

  // ── Helper: skip if typing in editable field ─────────────────────────
  function isTypingTarget(el){
    if (!el) return false;
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
  }

  // ── Global keyboard shortcuts ────────────────────────────────────────
  document.addEventListener('keydown', function(e){
    // ESC — close any open modal (looks for .open modal backdrops)
    if (e.key === 'Escape'){
      // Info modal (common ID across pages)
      const info = document.getElementById('infoBackdrop');
      if (info && info.classList.contains('open')){
        if (typeof closeInfoModal === 'function') closeInfoModal();
        else { info.classList.remove('open'); document.body.style.overflow=''; }
        e.preventDefault();
        return;
      }
      // Ticker / chart modal (flow.html, chart.html)
      const modal = document.getElementById('modalBackdrop');
      if (modal && modal.classList.contains('open')){
        if (typeof closeModal === 'function') closeModal();
        else { modal.classList.remove('open'); document.body.style.overflow=''; }
        e.preventDefault();
        return;
      }
      // Generic .modal.open
      const anyOpen = document.querySelector('.modal-backdrop.open, .modal.open');
      if (anyOpen){
        anyOpen.classList.remove('open');
        document.body.style.overflow='';
        e.preventDefault();
      }
      return;
    }

    // Skip typing fields for single-key shortcuts
    if (isTypingTarget(e.target)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    // "/" — focus ticker filter
    if (e.key === '/'){
      const filter = document.getElementById('tickerFilter');
      if (filter){
        e.preventDefault();
        filter.focus();
        filter.select && filter.select();
      }
      return;
    }

    // "?" — open info/help modal
    if (e.key === '?'){
      if (typeof openInfoModal === 'function'){
        e.preventDefault();
        openInfoModal();
      }
      return;
    }

    // "h" — go to Hub
    if (e.key === 'h' || e.key === 'H'){
      e.preventDefault();
      window.location.href = '/hub';
      return;
    }
  });

  // ── Clear button for ticker filter (injected if markup exists) ───────
  document.addEventListener('DOMContentLoaded', function(){
    const filter = document.getElementById('tickerFilter');
    if (!filter) return;

    // Find wrapper to position clear button inside
    const wrap = filter.closest('.ticker-search-wrap');
    if (!wrap) return;

    // Avoid duplicates
    if (wrap.querySelector('.input-clear')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'input-clear';
    btn.setAttribute('aria-label', 'Clear ticker filter');
    btn.innerHTML = '×';
    btn.addEventListener('click', function(){
      filter.value = '';
      filter.dispatchEvent(new Event('input', { bubbles: true }));
      filter.focus();
      btn.classList.remove('visible');
    });
    wrap.appendChild(btn);

    filter.addEventListener('input', function(){
      btn.classList.toggle('visible', filter.value.length > 0);
    });
    // Initial state
    btn.classList.toggle('visible', filter.value.length > 0);
  });

  // ── Directional arrow helper (opt-in) ────────────────────────────────
  // Usage in page templates:
  //   ZenithUI.sign(value)  →  "▲ +1.23"  /  "▼ -0.45"  /  "◆ 0.00"
  window.ZenithUI = window.ZenithUI || {};
  window.ZenithUI.sign = function(n, opts){
    opts = opts || {};
    const decimals = opts.decimals != null ? opts.decimals : 2;
    const suffix   = opts.suffix || '';
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    const abs = Math.abs(n).toFixed(decimals);
    if (n > 0)  return '▲ +' + abs + suffix;
    if (n < 0)  return '▼ -' + abs + suffix;
    return '◆ ' + abs + suffix;
  };
  window.ZenithUI.arrow = function(n){
    if (n === null || n === undefined || Number.isNaN(n)) return '';
    if (n > 0) return '▲';
    if (n < 0) return '▼';
    return '◆';
  };
})();
