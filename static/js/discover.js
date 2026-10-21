// Home page "people you may love to meet": carousel arrows, "Say hi" without reloading, "not now" to hide a card.
(function () {
  function csrf(form) {
    var i = form.querySelector('input[name=csrfmiddlewaretoken]');
    return i ? i.value : '';
  }

  function burst(el) {
    var r = el.getBoundingClientRect();
    ['💗', '💕', '💖', '💞', '❤️'].forEach(function (h, i) {
      var s = document.createElement('span');
      s.className = 'heart-burst';
      s.textContent = h;
      s.style.left = (r.left + r.width / 2) + 'px';
      s.style.top = (r.top + r.height / 2) + 'px';
      s.style.setProperty('--dx', ((i - 2) * 22) + 'px');
      document.body.appendChild(s);
      setTimeout(function () { s.remove(); }, 1000);
    });
  }

  function toast(text, level) {
    var box = document.querySelector('.toasts');
    if (!box) { box = document.createElement('div'); box.className = 'toasts'; box.setAttribute('role', 'status'); document.body.appendChild(box); }
    var t = document.createElement('div');
    t.className = 'toast toast-' + (level || 'success');
    t.textContent = text;
    box.appendChild(t);
    setTimeout(function () { t.classList.add('toast-hide'); }, 4000);
    setTimeout(function () { t.remove(); }, 4600);
  }

  document.querySelectorAll('[data-carousel]').forEach(function (wrap) {
    var track = wrap.querySelector('.discover-track');
    var prev = wrap.querySelector('.discover-arrow.prev');
    var next = wrap.querySelector('.discover-arrow.next');

    function sync() {
      prev.hidden = track.scrollLeft < 10;
      next.hidden = track.scrollLeft + track.clientWidth >= track.scrollWidth - 10;
    }
    function step(dir) {
      var card = track.querySelector('.pcard');
      track.scrollBy({ left: dir * ((card ? card.offsetWidth : 220) + 16) * 2, behavior: 'smooth' });
    }
    prev.addEventListener('click', function () { step(-1); });
    next.addEventListener('click', function () { step(1); });
    track.addEventListener('scroll', sync, { passive: true });
    window.addEventListener('resize', sync);
    sync();

    // "Not now": slide the card away
    track.addEventListener('click', function (e) {
      var skip = e.target.closest('button.pcard-skip[type=button]');
      if (!skip) return;
      var card = skip.closest('.pcard');
      card.classList.add('leaving');
      setTimeout(function () {
        card.remove();
        sync();
        if (!track.querySelector('.pcard')) {
          wrap.hidden = true;
          var done = document.getElementById('discover-done');
          if (done) done.hidden = false;
        }
        var pill = document.getElementById('discover-count');
        if (pill) {
          var n = track.querySelectorAll('.pcard').length;
          pill.textContent = n ? n + ' picks for you' : 'all caught up';
        }
      }, 320);
    });

    // "Say hi": send the request in the background
    track.addEventListener('submit', function (e) {
      var form = e.target.closest('form.js-request');
      if (!form) return;
      e.preventDefault();
      var btn = form.querySelector('button');
      btn.classList.add('busy');
      btn.textContent = 'Sending…';
      fetch(form.action, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf(form), 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' }
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          btn.classList.remove('busy');
          if (d.state === 'connected' && d.chat_url) {
            var a = document.createElement('a');
            a.className = 'pcard-link';
            a.href = d.chat_url;
            a.textContent = 'Open chat 💬';
            form.replaceChildren(a);
            burst(a);
          } else if (d.ok) {
            btn.textContent = 'Requested ✓';
            btn.classList.add('done');
            btn.disabled = true;
            burst(btn);
          } else {
            btn.textContent = 'Say hi 💗';
          }
          toast(d.message, d.ok ? 'success' : 'error');
        })
        .catch(function () { form.submit(); });   // no JS fetch support / network hiccup: normal form post
    });
  });
})();
