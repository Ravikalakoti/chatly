// Notification bell: polls the server, shows the unseen count, and marks everything seen when opened.
(function () {
  var root = document.getElementById('bell');
  if (!root) return;
  var btn = document.getElementById('bell-btn');
  var badge = document.getElementById('bell-badge');
  var panel = document.getElementById('bell-panel');
  var list = document.getElementById('bell-list');
  var latest = { unseen: 0, items: [] };
  var originalTitle = document.title;

  function setBadge(n) {
    badge.hidden = n <= 0;
    badge.textContent = n > 99 ? '99+' : String(n);
    document.title = n > 0 ? '(' + n + ') ' + originalTitle : originalTitle;
  }

  function render(items) {
    list.textContent = '';
    if (!items.length) {
      var p = document.createElement('p');
      p.className = 'bell-empty';
      p.textContent = 'Nothing yet. Your love notes will show up here 💞';
      list.appendChild(p);
      return;
    }
    items.forEach(function (n) {
      var a = document.createElement('a');
      a.className = 'bell-item' + (n.seen ? '' : ' unseen');
      a.href = n.url;
      var av = document.createElement('span');
      av.className = 'avatar av-' + n.color;
      if (n.avatar) {
        var img = document.createElement('img');
        img.src = n.avatar; img.alt = '';
        av.appendChild(img);
      } else {
        av.textContent = n.initial;
      }
      var body = document.createElement('span');
      body.className = 'bell-body';
      var t = document.createElement('span');
      t.className = 'bell-text';
      t.textContent = n.text;
      var ago = document.createElement('small');
      ago.textContent = n.ago;
      body.appendChild(t); body.appendChild(ago);
      a.appendChild(av); a.appendChild(body);
      list.appendChild(a);
    });
  }

  function load() {
    return fetch(root.dataset.listUrl, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        latest = data;
        if (panel.hidden) setBadge(data.unseen);   // keep the highlight while the menu is open
        else render(data.items);
      })
      .catch(function () {});
  }

  function markSeen() {
    fetch(root.dataset.seenUrl, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': root.dataset.csrf } })
      .catch(function () {});
    setBadge(0);
  }

  function open() {
    render(latest.items);          // unseen ones are still highlighted here
    panel.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    if (latest.unseen > 0) markSeen();
  }
  function close() {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
  }

  btn.addEventListener('click', function (e) { e.stopPropagation(); panel.hidden ? open() : close(); });
  document.addEventListener('click', function (e) { if (!root.contains(e.target)) close(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) load(); });

  load();
  setInterval(function () { if (!document.hidden) load(); }, 15000);
})();
