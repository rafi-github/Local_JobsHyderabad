"""ATS fill helpers ported from open-source apply engines.

Sources (MIT / public patterns), adapted for this Playwright + Copilot runner:
- Dropdown strategies + submit retry: https://github.com/devdattatalele/auto-apply
  (lib/fields.mjs, lib/engine.mjs clickSubmitButton)
- React native value setter: same idea as Job App Filler / ats-autofill-engine

Do not launch a second browser or a second autofill extension — Simplify Copilot
already owns the Chrome profile. These helpers fill leftover fields Copilot misses
and click the real ATS Submit (not Copilot's #proxy-submit-button overlay).
"""
from __future__ import annotations

import re

NATIVE_SET_JS = """(el, value) => {
  if (!el) return false;
  const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
  if (desc && desc.set) desc.set.call(el, value);
  else el.value = value;
  el.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
  el.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
  try { el.dispatchEvent(new Event('blur', {bubbles: true})); } catch (e) {}
  return true;
}"""

OPTION_SELECTORS = (
    '[data-automation-id="promptOption"]',
    '[role="option"]',
    ".select__option",
    ".select2-results__option",
    "li[class*='option']",
    ".dropdown-item",
    "div[data-value]",
    "[class*='MenuItem']",
    ".cx-select__list-item",
    ".oj-listbox-result-label",
)

PLACEHOLDER_VALUES = {
    "", "select", "select...", "choose", "please select", "please specify",
    "select an option", "select one", "select a value", "select...", "--",
    "n/a", "none", "type to search", "search", "pick one",
}

SCAN_REQUIRED_EMPTY_JS = """() => {
  const ph = new Set(['', 'select', 'select...', 'choose', 'please select', 'please specify',
    'select an option', 'select one', 'select a value', '--', 'type to search', 'search', 'pick one']);
  const questionLabel = (el) => {
    let label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
    if (!label && el.id) {
      const forLab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (forLab) label = forLab.innerText;
    }
    const wrap = el.closest('fieldset, [class*="question" i], [class*="Question"], [data-test-id], li, .field, label, [role="group"], spl-form-field, spl-autocomplete');
    if (wrap) {
      const t = wrap.querySelector('legend, label, [class*="label" i], h2, h3, h4, p, span');
      const text = (t && t.innerText) || wrap.innerText;
      if (text && text.trim().length > (label || '').length) label = text;
    }
    if (!label) {
      const prev = el.previousElementSibling;
      if (prev) label = prev.innerText;
    }
  return String(label || '').replace(/\\s+/g, ' ').trim().slice(0, 220);
  };
  const isRequired = (el, label) => {
    if (el.required) return true;
    if (el.getAttribute('aria-required') === 'true') return true;
    if (/[*✱]|\\(required\\)|required field/i.test(label)) return true;
    const wrap = el.closest('.required, .field-required, [class*="required" i], .ng-invalid, spl-autocomplete[errorstate]');
    if (wrap && /required|\\*/.test((wrap.className && wrap.className.toString()) || '') ) return true;
    if (el.getAttribute('aria-invalid') === 'true') return true;
    return false;
  };
  const isEmptyValue = (el, type, value, options) => {
    const v = (value || '').trim().toLowerCase();
    if (type === 'checkbox' || type === 'radio') return !el.checked;
    if (el.tagName === 'SELECT') {
      if (!v || ph.has(v)) return true;
      const opt = el.options[el.selectedIndex];
      const t = ((opt && opt.text) || '').trim().toLowerCase();
      return !t || ph.has(t);
    }
    if (el.getAttribute('role') === 'combobox' || type === 'combobox') {
      return !v || ph.has(v);
    }
    return !v || ph.has(v);
  };
  const items = [];
  const seen = new Set();
  const nodes = document.querySelectorAll('input, textarea, select, [role="combobox"]');
  for (const el of nodes) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'file', 'submit', 'button', 'password', 'image'].includes(type)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 6 && r.height < 6 && type !== 'checkbox' && type !== 'radio') continue;
    const label = questionLabel(el);
    if (!isRequired(el, label) && !el.getAttribute('aria-invalid')) continue;
    let value = '';
    let options = [];
    if (type === 'checkbox' || type === 'radio') {
      value = el.checked ? 'checked' : '';
    } else if (el.tagName === 'SELECT') {
      const opt = el.options[el.selectedIndex];
      value = ((opt && opt.text) || el.value || '').trim();
      options = Array.from(el.options).map(o => (o.text || '').trim()).filter(Boolean).slice(0, 40);
    } else {
      value = (el.value || el.innerText || '').trim();
    }
    if (!isEmptyValue(el, type, value, options)) continue;
    const key = (el.id || el.name || '') + '|' + label.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    items.push({
      id: el.id || '',
      name: el.name || '',
      label,
      type,
      options,
      required: true,
    });
  }
  // Unchecked required radio groups (legend shows * but no input checked)
  for (const fs of document.querySelectorAll('fieldset')) {
    const leg = fs.querySelector('legend');
    const lab = (leg && leg.innerText) || '';
    if (!/[*✱]|required/i.test(lab)) continue;
    const radios = fs.querySelectorAll('input[type=radio]');
    if (!radios.length) continue;
    let any = false;
    for (const r of radios) { if (r.checked) { any = true; break; } }
    if (any) continue;
    const key = 'fieldset|' + lab.toLowerCase().slice(0, 80);
    if (seen.has(key)) continue;
    seen.add(key);
    items.push({
      id: '',
      name: (radios[0] && radios[0].name) || '',
      label: lab.replace(/\\s+/g, ' ').trim().slice(0, 220),
      type: 'radio',
      options: Array.from(radios).map(r => {
        const lb = r.id ? document.querySelector('label[for="' + CSS.escape(r.id) + '"]') : null;
        return ((lb && lb.innerText) || r.value || '').trim();
      }).filter(Boolean).slice(0, 12),
      required: true,
    });
  }
  return items;
}"""

SCAN_VALIDATION_ERRORS_JS = """() => {
  const out = [];
  const push = (t) => {
    t = String(t || '').replace(/\\s+/g, ' ').trim();
    if (t.length < 6 || t.length > 200) return;
    if (out.includes(t)) return;
    out.push(t);
  };
  for (const el of document.querySelectorAll('[aria-invalid="true"], .error, .field-error, .validation-error, [class*="error-message" i], spl-autocomplete[errorstate]')) {
    push(el.innerText || el.getAttribute('aria-label') || '');
  }
  for (const el of document.querySelectorAll('input:invalid, select:invalid, textarea:invalid')) {
    const lab = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
    const name = ((lab && lab.innerText) || el.getAttribute('aria-label') || el.name || 'Field').trim();
    push(name + ' is required');
  }
  return out.slice(0, 16);
}"""

CLICK_ATS_SUBMIT_JS = """() => {
  const skipRe = /simplify|tailor resume|resume builder|proxy-submit|autofill/i;
  const wantRe = /^(submit application|submit your application|send application|complete application|submit)$/i;
  const hits = [];
  const inCopilot = (el) => {
    const id = (el.id || '') + ' ' + (el.className || '');
    if (skipRe.test(id)) return true;
    let n = el;
    for (let i = 0; i < 12 && n; i++) {
      const cn = (n.className && n.className.toString) ? n.className.toString() : '';
      const nid = n.id || '';
      if (skipRe.test(cn) || skipRe.test(nid) || nid === 'proxy-submit-button') return true;
      n = n.parentElement;
    }
    return false;
  };
  const fire = (el) => {
    el.scrollIntoView({block: 'center', inline: 'nearest'});
    const r = el.getBoundingClientRect();
    const x = r.left + Math.max(r.width / 2, 2);
    const y = r.top + Math.max(r.height / 2, 2);
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      el.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window, clientX: x, clientY: y}));
    }
    try { el.click(); } catch (e) {}
  };
  const walk = (root) => {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('button, a[role=button], [role=button], input[type=submit]').forEach((el) => {
      const t = ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '')
        .replace(/\\s+/g, ' ').trim();
      if (!t || t.length > 48 || el.disabled) return;
      if (!wantRe.test(t)) return;
      if (inCopilot(el)) return;
      const pe = getComputedStyle(el).pointerEvents;
      if (pe === 'none') return;
      const r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) return;
      hits.push({el, t, y: r.y, x: r.x});
    });
    root.querySelectorAll('*').forEach((el) => { if (el.shadowRoot) walk(el.shadowRoot); });
  };
  walk(document);
  if (!hits.length) return '';
  hits.sort((a, b) => b.y - a.y);
  fire(hits[0].el);
  return hits[0].t;
}"""


def fuzzy_score(needle: str, haystack: str) -> float:
    """Score two strings. Prefer whole words so 'India' does not win 'British Indian Ocean Territory'."""
    a = (needle or "").lower().strip()
    b = (haystack or "").lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if re.search(r"\b" + re.escape(a) + r"\b", b):
        extra = max(0, len(b.split()) - len(a.split()))
        return max(0.55, 0.95 - extra * 0.08)
    if re.search(r"\b" + re.escape(b) + r"\b", a):
        extra = max(0, len(a.split()) - len(b.split()))
        return max(0.5, 0.88 - extra * 0.08)
    aw, bw = a.split(), b.split()
    if not aw or not bw:
        return 0.0

    def word_hit(w: str, words: list[str]) -> bool:
        for x in words:
            if w == x:
                return True
            if len(w) >= 4 and abs(len(x) - len(w)) <= 1 and (x.startswith(w) or w.startswith(x)):
                return True
        return False

    overlap = sum(1 for w in aw if word_hit(w, bw))
    return overlap / max(len(aw), len(bw)) * 0.6


def best_option(needle: str, options: list[str]) -> str | None:
    """Pick the option that best matches needle. Short exact-ish beats long substring."""
    best = None
    best_score = 0.34
    for opt in options:
        text = (opt or "").strip()
        if not text or text.lower() in PLACEHOLDER_VALUES:
            continue
        score = fuzzy_score(needle, text)
        if score > best_score:
            best_score = score
            best = text
    return best


def native_fill(locator, value: str) -> bool:
    """Fill a React/controlled input so the ATS state actually updates."""
    try:
        locator.evaluate(NATIVE_SET_JS, str(value))
        return True
    except Exception:
        return False


def handle_dropdown(page, locator, value: str) -> bool:
    """Native select, type-to-filter, click-scan, then keyboard. From auto-apply."""
    if not value:
        return False
    try:
        if not locator.count():
            return False
        el = locator.first
        tag = (el.evaluate("n => (n.tagName || '').toLowerCase()") or "")
        if tag == "select":
            if _select_native(el, value):
                return True
        el.scroll_into_view_if_needed(timeout=1500)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        el.click(timeout=2000, force=True)
        page.wait_for_timeout(250)
        try:
            el.fill("")
            el.type(str(value)[:18], delay=35)
            page.wait_for_timeout(600)
        except Exception:
            pass
        if _click_best_option(page, value):
            return True
        try:
            page.keyboard.press("Escape")
            el.click(timeout=1500, force=True)
            page.wait_for_timeout(500)
        except Exception:
            pass
        if _click_best_option(page, value):
            return True
        for _ in range(12):
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(60)
            try:
                focused = page.locator(
                    ".select__option--is-focused, [role='option'][aria-selected='true']"
                ).first
                if focused.count():
                    text = (focused.inner_text() or "").strip()
                    if fuzzy_score(value, text) >= 0.5:
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(250)
                        return True
            except Exception:
                pass
        page.keyboard.press("Enter")
        return bool((el.input_value() or "").strip())
    except Exception:
        return False


def _select_native(el, value: str) -> bool:
    try:
        el.select_option(label=value, timeout=800)
        return True
    except Exception:
        pass
    try:
        el.select_option(value=value, timeout=800)
        return True
    except Exception:
        pass
    try:
        opts = el.evaluate(
            "e => [...e.options].map(o => ({v: o.value, t: (o.text || '').trim()}))"
        ) or []
    except Exception:
        return False
    labels = [o.get("t") or "" for o in opts]
    hit = best_option(value, labels)
    if not hit:
        return False
    for o in opts:
        if (o.get("t") or "").strip() == hit:
            try:
                el.select_option(value=o.get("v") or "", timeout=800)
                return True
            except Exception:
                try:
                    el.select_option(label=hit, timeout=800)
                    return True
                except Exception:
                    return False
    return False


def _click_best_option(page, value: str) -> bool:
    best = None
    best_score = 0.29
    for sel in OPTION_SELECTORS:
        try:
            loc = page.locator(sel)
            n = min(loc.count(), 40)
        except Exception:
            continue
        for i in range(n):
            opt = loc.nth(i)
            try:
                if not opt.is_visible():
                    continue
                text = (opt.inner_text() or "").strip()
            except Exception:
                continue
            if not text or len(text) > 90 or text.lower() == "no options":
                continue
            score = fuzzy_score(value, text)
            if score > best_score:
                best_score = score
                best = opt
    if best is None:
        return False
    try:
        best.click(timeout=1500, force=True)
        page.wait_for_timeout(250)
        return True
    except Exception:
        return False


def scan_required_empty(page) -> list:
    try:
        return page.evaluate(SCAN_REQUIRED_EMPTY_JS) or []
    except Exception:
        return []


def scan_validation_errors(page) -> list[str]:
    try:
        return page.evaluate(SCAN_VALIDATION_ERRORS_JS) or []
    except Exception:
        return []


def _fill_required_row(page, row: dict, infer, value: str) -> bool:
    """Fill one required empty control."""
    if not value and row.get("type") not in {"checkbox"}:
        return False
    ftype = (row.get("type") or "").lower()
    label = row.get("label") or ""
    eid = row.get("id") or ""
    name = row.get("name") or ""
    try:
        if ftype in {"checkbox"}:
            sel = f'#{eid}' if eid else f'[name="{name}"]'
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                try:
                    if not loc.is_checked():
                        loc.check(force=True, timeout=800)
                        return True
                except Exception:
                    loc.click(force=True, timeout=800)
                    return True
            return False
        if ftype == "radio":
            want = (value or "No").strip()
            try:
                scope = page.get_by_text(re.compile(re.escape(label[:50]), re.I)).first
                if scope.count():
                    box = scope.locator(
                        "xpath=ancestor::*[self::fieldset or self::li or self::div][1]"
                    )
                    opt = box.get_by_text(re.compile(rf"^{re.escape(want)}$", re.I)).first
                    if opt.count():
                        opt.click(timeout=1000, force=True)
                        return True
            except Exception:
                pass
            if name:
                loc = page.locator(f'input[type=radio][name="{name}"]').first
                if loc.count():
                    page.get_by_role("radio", name=re.compile(rf"^{re.escape(want)}$", re.I)).first.click(
                        timeout=1000, force=True
                    )
                    return True
            return False
        sel = f"#{eid}" if eid else (f'[name="{name}"]' if name else "")
        if not sel:
            return False
        loc = page.locator(sel).first
        if not loc.count() or not loc.is_visible():
            return False
        tag = (loc.evaluate("n => (n.tagName || '').toLowerCase()") or "")
        if tag == "select" or loc.get_attribute("role") == "combobox":
            options = row.get("options") or []
            chosen = best_option(str(value), options) or value
            return handle_dropdown(page, loc, str(chosen))
        if native_fill(loc, str(value)):
            return True
        loc.fill(str(value), timeout=1200)
        return True
    except Exception:
        return False


def fill_required_fields(page, infer, *, passes: int = 2) -> int:
    """Second pass: DOM scan for required empties HTML5 / aria / asterisk labels."""
    filled = 0
    for _ in range(passes):
        rows = scan_required_empty(page)
        if not rows:
            break
        round_n = 0
        for row in rows:
            label = row.get("label") or ""
            opts = row.get("options") or []
            want = infer(label, opts)
            if not want and row.get("type") in {"checkbox"}:
                want = "Yes"
            if not want:
                continue
            if _fill_required_row(page, row, infer, str(want)):
                round_n += 1
        filled += round_n
        if round_n == 0:
            break
        try:
            page.wait_for_timeout(350)
        except Exception:
            pass
    if filled:
        print(f"  Filled {filled} required empty field(s) from DOM scan.", flush=True)
    return filled


def commit_open_comboboxes(page, infer) -> int:
    """Type-ahead boxes with text but no committed list option block Next."""
    fixed = 0
    try:
        boxes = page.evaluate(
            """() => [...document.querySelectorAll('input[role=combobox], [role=combobox] input, select + input')]
              .map(el => {
                const r = el.getBoundingClientRect();
                return {
                  id: el.id, name: el.name,
                  value: (el.value || '').trim(),
                  invalid: el.getAttribute('aria-invalid') === 'true',
                  q: (el.getAttribute('aria-label') || el.placeholder || el.name || '').slice(0, 120),
                  vis: r.width > 8 && r.height > 8,
                };
              }).filter(x => x.vis && x.value)"""
        ) or []
    except Exception:
        return 0
    for box in boxes:
        val = (box.get("value") or "").strip()
        if not val or val.lower() in PLACEHOLDER_VALUES:
            continue
        if not box.get("invalid") and len(val) > 40:
            continue
        want = infer(box.get("q") or "", []) or val
        sel = f'#{box["id"]}' if box.get("id") else f'[name="{box.get("name")}"]'
        try:
            loc = page.locator(sel).first
            if loc.count() and handle_dropdown(page, loc, str(want)):
                fixed += 1
        except Exception:
            continue
    if fixed:
        print(f"  Committed {fixed} open combobox selection(s).", flush=True)
    return fixed


def fill_required_gaps(page, infer, *, passes: int = 2) -> int:
    """Run required scan, combobox commit, and dropdown fill before Next/Submit."""
    total = 0
    for _ in range(max(1, passes)):
        total += commit_open_comboboxes(page, infer)
        total += fill_required_fields(page, infer, passes=1)
        total += fill_empty_dropdowns(page, infer)
        try:
            page.wait_for_timeout(250)
        except Exception:
            pass
    return total


def fill_empty_dropdowns(page, infer) -> int:
    """Fill visible empty selects / comboboxes using inferred answers."""
    filled = 0
    try:
        boxes = page.evaluate(
            """() => [...document.querySelectorAll('select, input[role=combobox], [role=combobox]')]
              .map(el => {
                const r = el.getBoundingClientRect();
                const lab = el.id ? document.querySelector('label[for="'+el.id+'"]') : null;
                const wrap = el.closest('label, fieldset, [class*=question], li, div');
                const q = ((lab && lab.innerText) || (wrap && (wrap.querySelector('label,legend')||{}).innerText) || el.getAttribute('aria-label') || el.name || '')
                  .replace(/\\s+/g,' ').trim().slice(0,180);
                let value = '';
                let options = [];
                if (el.tagName === 'SELECT') {
                  const opt = el.options[el.selectedIndex];
                  value = ((opt && opt.text) || el.value || '').trim();
                  options = [...el.options].map(o => (o.text || '').trim()).filter(Boolean).slice(0, 40);
                } else value = (el.value || el.innerText || '').trim();
                return {id: el.id, name: el.name, q, value, options, vis: r.width>8 && r.height>8, tag: el.tagName};
              }).filter(x => x.vis)"""
        ) or []
    except Exception:
        return 0
    for box in boxes:
        cur = (box.get("value") or "").strip()
        if cur and cur.lower() not in PLACEHOLDER_VALUES:
            continue
        opts = box.get("options") or []
        want = infer(box.get("q") or "", opts)
        if not want:
            continue
        chosen = best_option(str(want), opts) or want
        sel = f'[id="{box["id"]}"]' if box.get("id") else f'[name="{box.get("name")}"]'
        try:
            loc = page.locator(sel).first
            if loc.count() and handle_dropdown(page, loc, str(chosen)):
                filled += 1
        except Exception:
            continue
    if filled:
        print(f"  Filled {filled} dropdown(s) with open-source ATS handlers.", flush=True)
    return filled


def fill_phenom_acknowledgment(page) -> int:
    """Phenom loops Copilot Next until the applicant-acknowledgment boxes are checked."""
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    if "phenom" not in url and "thermofisher" not in url and "stepname=" not in url:
        try:
            blob = (page.inner_text("body") or "")[:1500]
        except Exception:
            blob = ""
        if not re.search(r"acknowledg", blob, re.I):
            return 0
    n = 0
    try:
        n = page.evaluate(
            """() => {
              let n = 0;
              const re = /acknowledg|agree|consent|certify|i have read|terms|privacy/i;
              for (const el of document.querySelectorAll('input[type=checkbox]')) {
                const wrap = el.closest('label') || el.parentElement || el;
                const t = ((wrap.innerText || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.id || ''));
                if (!re.test(t) || el.checked) continue;
                el.checked = true;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                try { wrap.click(); } catch (e) {}
                n++;
              }
              return n;
            }"""
        ) or 0
    except Exception:
        n = 0
    if n:
        print(f"  Checked {n} Phenom acknowledgment box(es).", flush=True)
    return n


def click_ats_submit(page) -> bool:
    """Click the real ATS Submit, skipping Copilot's overlay proxy. From auto-apply engine.mjs."""
    try:
        hit = page.evaluate(CLICK_ATS_SUBMIT_JS) or ""
    except Exception:
        hit = ""
    if hit:
        print(f"  Clicked ATS submit '{hit}' (open-source handler, skipped Copilot overlay).", flush=True)
        try:
            page.wait_for_timeout(3000)
        except Exception:
            pass
        return True
    for name in (
        r"^Submit application$",
        r"^Submit Application$",
        r"^Submit your application$",
        r"^Send application$",
        r"^Complete application$",
        r"^Submit$",
    ):
        try:
            loc = page.get_by_role("button", name=re.compile(name, re.I)).first
            if not loc.count() or not loc.is_visible() or not loc.is_enabled():
                continue
            el_id = (loc.get_attribute("id") or "") + " " + (loc.inner_text() or "")
            if re.search(r"proxy-submit|simplify|tailor", el_id, re.I):
                continue
            loc.scroll_into_view_if_needed(timeout=2000)
            loc.click(timeout=2500, force=True)
            print(f"  Clicked ATS submit via role '{name}'.", flush=True)
            page.wait_for_timeout(3000)
            return True
        except Exception:
            continue
    return False
