/**
 * Shared utilities for Stock Monitor App
 */
'use strict';

/**
 * Escape HTML entities to prevent XSS in template literals.
 * Use: innerHTML = `<td>${esc(data.name)}</td>`
 */
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Set element text content safely (no HTML parsing).
 * Preferred over innerHTML for dynamic content.
 */
function setText(el, text) {
  if (typeof el === 'string') el = document.getElementById(el);
  if (el) el.textContent = text == null ? '' : String(text);
}

/**
 * Create an element with text content.
 */
function el(tag, text, className) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = String(text);
  if (className) e.className = className;
  return e;
}
