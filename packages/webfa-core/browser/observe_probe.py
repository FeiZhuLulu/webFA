from __future__ import annotations


OBSERVE_PROBE = r"""
(opts) => {
  const maxChars = opts.maxChars;
  const blockChars = opts.blockChars;
  const blockCount = opts.blockCount;
  const isVisible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const nameOf = (el) => (
    el.getAttribute('aria-label') ||
    el.getAttribute('title') ||
    el.getAttribute('placeholder') ||
    el.getAttribute('name') ||
    textOf(el) ||
    el.value ||
    ''
  ).trim();
  const roleOf = (el) => {
    const role = el.getAttribute('role');
    if (role) return role;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'combobox';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'submit' || type === 'button') return 'button';
      return 'textbox';
    }
    return tag;
  };
  const actionsFor = (el, role) => {
    const tag = el.tagName.toLowerCase();
    if (role === 'textbox') return ['click', 'type', 'clear', 'focus', 'press'];
    if (role === 'link') return ['click', 'focus', 'follow_link'];
    if (role === 'button') return ['click', 'focus', 'activate_control'];
    if (role === 'combobox') return ['click', 'select', 'focus', 'press', 'choose_option'];
    if (role === 'checkbox' || role === 'radio') return ['click', 'check', 'uncheck', 'focus'];
    if (el.isContentEditable) return ['click', 'type', 'clear', 'focus', 'press'];
    return tag === 'option' ? ['select'] : ['click', 'focus'];
  };
  const labelFor = (el) => {
    const id = el.getAttribute('id');
    if (id) {
      const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (label) return textOf(label);
    }
    const parentLabel = el.closest('label');
    return parentLabel ? textOf(parentLabel) : '';
  };
  const fieldKeyFor = (el) => (
    el.getAttribute('name') ||
    labelFor(el) ||
    el.getAttribute('placeholder') ||
    el.getAttribute('aria-label') ||
    el.getAttribute('id') ||
    ''
  ).trim();
  const selector = [
    'a[href]', 'button', 'input', 'textarea', 'select',
    '[role="button"]', '[role="link"]', '[contenteditable="true"]',
    '[role="row"]', '[role="listitem"]', '[role="option"]', '[role="menuitem"]',
    'tr', '[onclick]', '[tabindex]:not([tabindex="-1"])'
  ].join(',');
  const idPattern = /^el_(\d+)$/;
  let nextId = Array.from(document.querySelectorAll('[data-webfa-id]')).reduce((max, el) => {
    const match = idPattern.exec(el.getAttribute('data-webfa-id') || '');
    return match ? Math.max(max, Number(match[1]) + 1) : max;
  }, 1);
  const usedIds = new Set();
  const allocateId = (el) => {
    let id = el.getAttribute('data-webfa-id') || '';
    if (!idPattern.test(id) || usedIds.has(id)) {
      do {
        id = `el_${nextId++}`;
      } while (usedIds.has(id));
      el.setAttribute('data-webfa-id', id);
    }
    usedIds.add(id);
    return id;
  };
  const elements = Array.from(document.querySelectorAll(selector))
    .filter(isVisible)
    .slice(0, 200)
    .map((el) => {
      const id = allocateId(el);
      const role = roleOf(el);
      const tag = el.tagName.toLowerCase();
      return {
        id, role, tag,
        name: nameOf(el),
        text: textOf(el),
        value: el.value || '',
        placeholder: el.getAttribute('placeholder') || '',
        input_type: tag === 'input' ? (el.getAttribute('type') || 'text') : null,
        visible: true,
        enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
        checked: typeof el.checked === 'boolean' ? el.checked : null,
        selected: typeof el.selected === 'boolean' ? el.selected : null,
        href: el.href || null,
        actions: actionsFor(el, role)
      };
    });
  const forms = Array.from(document.querySelectorAll('form')).slice(0, 50).map((form, index) => {
    const formElements = Array.from(form.querySelectorAll('input, textarea, select')).filter(isVisible);
    const fields = formElements.map((el) => el.getAttribute('data-webfa-id')).filter(Boolean);
    const fieldDetails = formElements.map((el) => {
      const tag = el.tagName.toLowerCase();
      return {
        id: el.getAttribute('data-webfa-id') || '',
        key: fieldKeyFor(el),
        label: labelFor(el),
        name: el.getAttribute('name') || '',
        placeholder: el.getAttribute('placeholder') || '',
        value: el.value || '',
        type: tag === 'input' ? (el.getAttribute('type') || 'text') : tag,
        required: !!el.required,
        enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true'
      };
    }).filter((field) => field.id && field.key);
    const submit = Array.from(form.querySelectorAll('button,input[type="submit"]')).map((el) => el.getAttribute('data-webfa-id')).find(Boolean) || null;
    const text = textOf(form).slice(0, 500);
    return { id: `form_${index + 1}`, label: text.split(' ').slice(0, 8).join(' '), text, fields, field_details: fieldDetails, submit };
  });
  const blockTypeOf = (el) => {
    const role = el.getAttribute('role');
    if (role === 'listitem') return 'list_item';
    const tag = el.tagName.toLowerCase();
    if (tag === 'h1' || tag === 'h2' || tag === 'h3') return 'heading';
    if (tag === 'p') return 'paragraph';
    if (tag === 'li') return 'list_item';
    if (tag === 'form') return 'form';
    if (tag === 'nav') return 'nav';
    if (tag === 'article') return 'generic';
    return 'generic';
  };
  const blockSelector = 'h1, h2, h3, p, li, article, form, nav, tr, [role="listitem"], [role="row"], [role="option"]';
  const blockSeen = new WeakSet();
  const contentBlocks = [];
  for (const el of document.querySelectorAll(blockSelector)) {
    if (contentBlocks.length >= blockCount) break;
    if (blockSeen.has(el)) continue;
    if (el.parentElement && blockSeen.has(el.parentElement)) continue;
    if (!isVisible(el)) continue;
    const text = textOf(el);
    if (!text) continue;
    blockSeen.add(el);
    const ownId = el.getAttribute('data-webfa-id');
    const elementIds = [
      ownId,
      ...Array.from(el.querySelectorAll('[data-webfa-id]'))
      .map((node) => node.getAttribute('data-webfa-id'))
    ].filter((id) => idPattern.test(id || ''));
    contentBlocks.push({
      id: `block_${contentBlocks.length + 1}`,
      type: blockTypeOf(el),
      text: text.slice(0, blockChars),
      element_ids: Array.from(new Set(elementIds))
    });
  }
  const active = document.activeElement && document.activeElement.getAttribute('data-webfa-id');
  const visibleText = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim().slice(0, maxChars);
  return {
    loading: document.readyState !== 'complete',
    focused_element_id: active || null,
    visible_text: visibleText,
    interactive_elements: elements,
    content_blocks: contentBlocks,
    forms
  };
}
"""
