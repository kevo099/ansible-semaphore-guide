/* The setup page's form and step list. All text that depends on an answer is set as
 * text, never as markup, and plan.js refuses values that could change a command. */
(function () {
  'use strict';

  var plan = window.GuidePlan;
  var PANELS = [
    { id: 'basics', label: 'Basics', fields: ['admin'] },
    { id: 'access', label: 'Access', fields: ['address', 'release'] },
    { id: 'steps', label: 'Your steps', fields: [] }
  ];
  var SYSTEM_HINTS = { rhel: 'Registered with Red Hat, or Azure\'s pay-as-you-go image.' };
  var EXPOSURES = {
    tunnel: { label: 'An SSH tunnel', hint: 'Recommended. Nothing new listens on the network: you forward one local port over SSH.' },
    https: { label: 'HTTPS on the VM\'s address', hint: 'nginx on port 443, with a self-signed certificate that you check by its fingerprint.' }
  };

  var answers = plan.decode(window.location.hash);
  var current = 0;
  var done = {};

  function byId(id) { return document.getElementById(id); }

  function el(tag, properties, children) {
    var node = document.createElement(tag);
    Object.keys(properties || {}).forEach(function (name) {
      if (name === 'text') { node.textContent = properties[name]; }
      else if (name === 'className') { node.className = properties[name]; }
      else { node.setAttribute(name, properties[name]); }
    });
    (children || []).forEach(function (child) { if (child) { node.appendChild(child); } });
    return node;
  }

  function say(message) {
    var status = byId('status');
    status.textContent = '';
    window.setTimeout(function () { status.textContent = message; }, 30);
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(function () { return copyFromField(text); });
    }
    return copyFromField(text);
  }

  // Without HTTPS the clipboard API is not there, and a browser may refuse it; a selected,
  // off-screen field still copies.
  function copyFromField(text) {
    return new Promise(function (resolve, reject) {
      var area = el('textarea', { className: 'offscreen', readonly: '', 'aria-hidden': 'true', tabindex: '-1' });
      area.value = text;
      document.body.appendChild(area);
      area.select();
      var copied = false;
      try { copied = document.execCommand('copy'); } catch (error) { copied = false; }
      document.body.removeChild(area);
      if (copied) { resolve(); } else { reject(new Error('copy refused')); }
    });
  }

  function copyButton(text, label, what, of) {
    var button = el('button', { type: 'button', className: 'copy', text: label, 'aria-label': label + ': ' + of });
    button.addEventListener('click', function () {
      copyText(text).then(function () {
        button.textContent = 'Copied';
        button.focus();
        say(what + ' copied.');
        window.setTimeout(function () { button.textContent = label; }, 1600);
      }, function () {
        say('This browser did not allow the copy. Select the text and copy it yourself.');
      });
    });
    return button;
  }

  function download(name, content) {
    var link = el('a', { href: URL.createObjectURL(new Blob([content], { type: 'text/yaml' })), download: name });
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  }

  function cards(containerId, name, options, selected, hints) {
    var container = byId(containerId);
    container.textContent = '';
    Object.keys(options).forEach(function (key) {
      var input = el('input', { type: 'radio', name: name, value: key });
      input.checked = key === selected;
      input.addEventListener('change', function () { answers[name] = key; refreshForm(); });
      var hint = (hints && hints[key]) || options[key].hint || '';
      container.appendChild(el('label', { className: 'card' }, [
        input, el('strong', { text: options[key].label }), hint ? el('span', { text: hint }) : null
      ]));
    });
  }

  function showError(field, message) {
    var input = byId(field);
    var error = byId(field + '-error');
    error.hidden = !message;
    error.textContent = message || '';
    if (message) { input.setAttribute('aria-invalid', 'true'); } else { input.removeAttribute('aria-invalid'); }
  }

  function readInputs() {
    ['admin', 'address', 'release'].forEach(function (field) { answers[field] = byId(field).value.trim(); });
    answers = plan.normalize(answers);
  }

  // Everything on the two form panels that depends on another answer.
  function refreshForm() {
    readInputs();
    var system = plan.SYSTEMS[answers.system];
    byId('admin').placeholder = answers.platform === 'seed' ? system.defaultUser :
      (answers.platform === 'azure' ? 'azureuser' : 'your login');
    var reason = plan.method(answers).reason;
    byId('method-reason').hidden = !reason;
    byId('method-reason').textContent = reason;
    byId('address-field').hidden = answers.expose !== 'https';
    updateAddress();
  }

  function updateAddress() {
    var view = current === 2 ? '&view=steps' : '';
    var hash = plan.encode(answers) + view;
    window.history.replaceState(null, '', hash ? '#' + hash.replace(/^&/, '') : window.location.pathname + window.location.search);
  }

  // The first panel, up to and including `last`, that has a wrong value; -1 when none has.
  function firstInvalid(last) {
    readInputs();
    var errors = plan.validate(answers);
    var found = -1;
    PANELS.forEach(function (panel, index) {
      panel.fields.forEach(function (field) {
        var message = index <= last ? errors[field] : '';
        showError(field, message);
        if (message && found === -1) { found = index; }
      });
    });
    return found;
  }

  function show(index) {
    var invalid = index > 0 ? firstInvalid(index - 1) : -1;
    if (invalid !== -1) { index = invalid; }
    current = index;
    PANELS.forEach(function (panel, at) { byId('panel-' + panel.id).hidden = at !== current; });
    Array.prototype.forEach.call(byId('stepper').querySelectorAll('button'), function (button, at) {
      if (at === current) { button.setAttribute('aria-current', 'step'); } else { button.removeAttribute('aria-current'); }
    });
    byId('previous').hidden = current === 0;
    byId('next').hidden = current === PANELS.length - 1;
    byId('next').textContent = current === PANELS.length - 2 ? 'Show my steps' : 'Next: ' + PANELS[Math.min(current + 1, 2)].label;
    if (current === 2) { renderSteps(); }
    updateAddress();
    if (invalid !== -1) {
      var wrong = PANELS[invalid].fields.filter(function (field) { return !byId(field + '-error').hidden; })[0];
      if (wrong === 'release') { byId('release').closest('details').open = true; }
      if (wrong) { byId(wrong).focus(); }
    } else {
      byId('main').focus();
      window.scrollTo(0, 0);
    }
  }

  function summaryItem(term, value) {
    return el('div', {}, [el('dt', { text: term }), el('dd', { text: value })]);
  }

  function renderStep(step, total) {
    var item = el('li', { className: 'step' + (done[step.id] ? ' done' : '') });
    item.appendChild(el('h3', { text: step.title }));
    item.appendChild(el('span', { className: 'where', text: 'Where: ' + step.where }));
    step.text.forEach(function (paragraph) { item.appendChild(el('p', { text: paragraph })); });
    if (step.list.length) {
      item.appendChild(el('ol', { className: 'todo' }, step.list.map(function (entry) { return el('li', { text: entry }); })));
    }
    if (step.file) {
      item.appendChild(el('div', { className: 'file-actions' }, [
        copyButton(step.file.content, 'Copy the file', 'The file', step.title),
        (function () {
          var button = el('button', { type: 'button', className: 'download', text: 'Download ' + step.file.name });
          button.addEventListener('click', function () { download(step.file.name, step.file.content); });
          return button;
        })()
      ]));
      item.appendChild(el('details', { className: 'file' }, [
        el('summary', { text: 'Show the file' }),
        el('div', { className: 'command-box' }, [el('pre', { text: step.file.content, tabindex: '0' })])
      ]));
    }
    step.commands.forEach(function (command) {
      item.appendChild(el('div', { className: 'command' }, [
        command.label ? el('div', { className: 'command-label', text: command.label }) : null,
        el('div', { className: 'command-box' }, [
          el('pre', { text: command.code, tabindex: '0' }),
          copyButton(command.code, 'Copy', 'The command', step.title + (command.label ? ', ' + command.label.toLowerCase() : ''))
        ])
      ]));
    });
    item.appendChild(el('p', { className: 'expect' }, [el('b', { text: 'You should see: ' }), document.createTextNode(step.expect)]));
    if (step.note) { item.appendChild(el('p', { className: 'note', text: step.note })); }
    if (step.links.length) {
      item.appendChild(el('ul', { className: 'links' }, step.links.map(function (link) {
        return el('li', {}, [el('a', { href: link.href, rel: 'noopener', target: '_blank', text: link.text })]);
      })));
    }
    if (step.checked) { item.appendChild(el('p', { className: 'checked', text: 'Checked: ' + step.checked })); }
    var box = el('input', { type: 'checkbox', 'aria-label': 'Done: ' + step.title });
    box.checked = Boolean(done[step.id]);
    box.addEventListener('change', function () {
      done[step.id] = box.checked;
      item.className = 'step' + (box.checked ? ' done' : '');
      showProgress(total);
    });
    item.appendChild(el('label', { className: 'done-toggle' }, [box, document.createTextNode('Done')]));
    return item;
  }

  function showProgress(total) {
    var count = Object.keys(done).filter(function (id) { return done[id]; }).length;
    byId('progress').textContent = count + ' of ' + total + ' steps done.';
  }

  function renderSteps() {
    var steps = plan.steps(answers);
    var known = {};
    steps.forEach(function (step) { known[step.id] = true; });
    Object.keys(done).forEach(function (id) { if (!known[id]) { delete done[id]; } });
    var summary = byId('summary');
    summary.textContent = '';
    [['Where', plan.PLATFORMS[answers.platform].label], ['System', plan.SYSTEMS[answers.system].label],
      ['Administrator', answers.admin],
      ['Access', answers.expose === 'https' ? 'HTTPS' + (answers.address ? ' at ' + answers.address : '') : 'SSH tunnel'],
      ['Release', answers.release]].forEach(function (pair) { summary.appendChild(summaryItem(pair[0], pair[1])); });
    var list = byId('steps');
    list.textContent = '';
    steps.forEach(function (step) { list.appendChild(renderStep(step, steps.length)); });
    showProgress(steps.length);
    byId('guide-link').setAttribute('href', plan.REPOSITORY + '/tree/' + answers.release);
    byId('guide-link').setAttribute('target', '_blank');
  }

  function start() {
    PANELS.forEach(function (panel, index) {
      var button = el('button', { type: 'button', text: (index + 1) + '  ' + panel.label });
      button.addEventListener('click', function () { show(index); });
      byId('stepper').appendChild(el('li', {}, [button]));
    });
    cards('platforms', 'platform', plan.PLATFORMS, answers.platform);
    cards('systems', 'system', plan.SYSTEMS, answers.system, SYSTEM_HINTS);
    cards('exposures', 'expose', EXPOSURES, answers.expose);
    byId('admin').value = answers.admin;
    byId('address').value = answers.address;
    byId('release').value = answers.release;
    ['admin', 'address', 'release'].forEach(function (field) {
      byId(field).addEventListener('input', function () { showError(field, ''); refreshForm(); });
      byId(field).addEventListener('keydown', function (event) {
        if (event.key === 'Enter') { event.preventDefault(); show(current + 1); }
      });
    });
    byId('previous').addEventListener('click', function () { show(current - 1); });
    byId('next').addEventListener('click', function () { show(current + 1); });
    byId('change').addEventListener('click', function () { show(0); });
    // A saved or shared address opens on the steps; with a value missing or wrong, on the
    // field that needs it, with the reason.
    var wantsSteps = /(^|[#&])view=steps(&|$)/.test(window.location.hash);
    refreshForm();
    show(wantsSteps ? 2 : 0);
  }

  start();
})();
