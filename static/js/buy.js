/*
 * "Buy more messages" page.
 * 1. Ask the server to create an order for the chosen pack.
 * 2. Razorpay mode: open Razorpay Checkout, then send the signed result to the server,
 *    which verifies it and adds the messages.
 *    Test mode (DEBUG, no keys): confirm a fake payment instead.
 */
(function () {
  'use strict';

  var cfg = JSON.parse(document.getElementById('buy-config').textContent);
  var statusBox = document.getElementById('buy-status');
  var buttons = Array.prototype.slice.call(document.querySelectorAll('[data-pack]'));
  var KINDS = ['text', 'voice', 'image'];

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function say(text, tone) {
    statusBox.textContent = text || '';
    statusBox.className = 'buy-status' + (tone ? ' ' + tone : '');
    statusBox.hidden = !text;
  }

  function busy(on) {
    buttons.forEach(function (b) { b.disabled = on; });
  }

  function post(url, data) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(data)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || 'Something went wrong. Please try again.');
        return d;
      });
    });
  }

  function updateBalances(q) {
    if (!q) return;
    KINDS.forEach(function (k) {
      var d = q[k];
      if (!d) return;
      var left = document.querySelector('[data-left="' + k + '"]');
      var bar = document.querySelector('[data-bar="' + k + '"]');
      var detail = document.querySelector('[data-detail="' + k + '"]');
      if (left) left.textContent = d.remaining + ' left';
      if (bar) bar.style.width = (d.limit ? Math.min(100, Math.round(100 * d.used / d.limit)) : 100) + '%';
      if (detail) {
        detail.textContent = d.used + ' of ' + d.limit + ' free used today' +
          (d.credits ? ' · ' + d.credits + ' bought' : '');
      }
    });
  }

  function paid(result) {
    updateBalances(result.quota);
    say('Payment received. Your messages have been added. 🎉', 'ok');
    busy(false);
  }

  function loadRazorpay() {
    return new Promise(function (resolve, reject) {
      if (window.Razorpay) { resolve(); return; }
      var s = document.createElement('script');
      s.src = 'https://checkout.razorpay.com/v1/checkout.js';
      s.onload = resolve;
      s.onerror = function () { reject(new Error('Could not load the payment window. Check your connection and try again.')); };
      document.head.appendChild(s);
    });
  }

  function razorpayFlow(order) {
    return loadRazorpay().then(function () {
      var rz = new window.Razorpay({
        key: order.key,
        amount: order.amount,
        currency: order.currency,
        name: order.name,
        description: order.description,
        order_id: order.order_id,
        prefill: order.prefill,
        theme: { color: '#ee4a7c' },
        handler: function (response) {
          say('Confirming your payment…');
          post(cfg.verifyUrl, response).then(paid).catch(function (e) {
            say(e.message + ' If money was taken, your messages will be added shortly.', 'err');
            busy(false);
          });
        },
        modal: { ondismiss: function () { say('Payment cancelled.'); busy(false); } }
      });
      rz.on('payment.failed', function (r) {
        say((r.error && r.error.description) || 'The payment failed. You have not been charged.', 'err');
        busy(false);
      });
      rz.open();
    });
  }

  function demoFlow(order) {
    if (!window.confirm('Test mode: pretend to pay for ' + order.description + '? No real money is charged.')) {
      busy(false);
      return null;
    }
    return post(cfg.demoUrl, { order_id: order.order_id }).then(paid);
  }

  function buy(pack) {
    say('');
    busy(true);
    post(cfg.orderUrl, { pack: pack })
      .then(function (order) { return order.mode === 'demo' ? demoFlow(order) : razorpayFlow(order); })
      .catch(function (e) { say(e.message, 'err'); busy(false); });
  }

  buttons.forEach(function (b) {
    b.addEventListener('click', function () { buy(b.dataset.pack); });
  });
})();
