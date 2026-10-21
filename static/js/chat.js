/*
 * Real-time chat client.
 *
 * One websocket per tab. The server pushes events (new messages, typing, read
 * receipts, new contacts) and this file keeps two things in sync:
 *   - the conversation list in the sidebar
 *   - the open conversation (if any)
 * Messages are always inserted with textContent, never innerHTML (no XSS).
 */
(function () {
  'use strict';

  const cfg = JSON.parse(document.getElementById('chat-config').textContent);
  const ME = cfg.me;
  const active = cfg.active;               // {id, name, initial, color, url} or null
  const activeId = active ? active.id : null;

  const $ = (sel) => document.querySelector(sel);
  const els = {
    quota: $('#quota-strip'),
    list: $('#conv-list'),
    empty: $('#list-empty'),
    search: $('#search'),
    banner: $('#conn-banner'),
    scroller: $('#messages'),
    inner: $('#messages-inner'),
    loadMore: $('#load-more'),
    form: $('#composer'),
    input: $('#msg-input'),
    sendBtn: $('#send-btn'),
    micBtn: $('#mic-btn'),
    photoInput: $('#photo-input'),
    recBar: $('#rec-bar'),
    recTime: $('#rec-time'),
    peerAvatar: $('#peer-avatar'),
    peerName: $('#peer-name'),
    peerStatus: $('#peer-status'),
  };

  const isTouch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
  const TITLE = 'Chats · Chatly';

  // ------------------------------------------------------------------ helpers
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function sameDay(a, b) { return a.toDateString() === b.toDateString(); }

  function clock(date) {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  function dayLabel(date) {
    const now = new Date();
    const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (sameDay(date, now)) return 'Today';
    if (sameDay(date, yesterday)) return 'Yesterday';
    return date.toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' });
  }

  function listTime(date) {
    const now = new Date();
    const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (sameDay(date, now)) return clock(date);
    if (sameDay(date, yesterday)) return 'Yesterday';
    return date.toLocaleDateString([], { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  function previewMsg(m) {
    if (m.kind === 'image') return '📷 ' + (previewOf(m.body || '') || 'Photo');
    if (m.kind === 'voice') return '🎤 Voice message';
    return previewOf(m.body);
  }

  function previewOf(body) {
    const flat = body.split(/\s+/).join(' ').trim();
    return flat.length <= 60 ? flat : flat.slice(0, 59) + '…';
  }

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  function toast(text) {
    let box = document.querySelector('.toasts');
    if (!box) {
      box = el('div', 'toasts');
      document.body.appendChild(box);
    }
    const t = el('div', 'toast toast-info', text);
    box.appendChild(t);
    t.addEventListener('click', () => t.classList.add('toast-hide'));
    setTimeout(() => t.classList.add('toast-hide'), 4500);
    setTimeout(() => t.remove(), 5200);
  }

  // A longer-lived toast that ends with a "Buy more" link (used when a daily limit is reached).
  function limitToast(text) {
    let box = document.querySelector('.toasts');
    if (!box) {
      box = el('div', 'toasts');
      document.body.appendChild(box);
    }
    const t = el('div', 'toast toast-info', (text || 'Daily limit reached.') + ' ');
    const link = el('a', null, 'Buy more');
    link.href = cfg.urls.buy;
    t.appendChild(link);
    box.appendChild(t);
    setTimeout(() => t.classList.add('toast-hide'), 9000);
    setTimeout(() => t.remove(), 9700);
  }

  // ------------------------------------------------- messages left (daily limits)
  const QUOTA_KINDS = [
    ['text', '💬', 'text messages'],
    ['voice', '🎤', 'voice messages'],
    ['image', '📸', 'photos'],
  ];

  function renderQuota(q) {
    if (!q || !els.quota) return;
    const chips = QUOTA_KINDS.map((k) => {
      const d = q[k[0]];
      if (!d) return null;
      const state = d.remaining === 0 ? ' empty' : d.remaining <= 2 ? ' low' : '';
      const chip = el('span', 'quota-chip' + state, k[1] + ' ' + d.remaining);
      chip.title = d.remaining + ' ' + k[2] + ' left' +
        (d.credits ? ' (' + d.free_left + ' free today + ' + d.credits + ' bought)' : ' (' + d.limit + ' free a day)');
      return chip;
    }).filter(Boolean);
    const buy = el('a', 'quota-buy', 'Buy more');
    buy.href = q.buy_url || cfg.urls.buy;
    els.quota.replaceChildren(el('span', 'quota-label', 'Left'), ...chips, buy);
  }

  // ------------------------------------------------------------------ sidebar
  const convs = new Map();
  cfg.conversations.forEach((c) => convs.set(c.id, c));
  if (activeId && convs.has(activeId)) convs.get(activeId).unread = 0;
  const typingTimers = new Map();          // conversation id -> timeout handle
  // Round avatar: profile photo if the person has one, otherwise a coloured initial.
  function avatarEl(c) {
      const d = el('div', 'avatar av-' + c.color);
      if (c.avatar) {
          const img = document.createElement('img');
          img.src = c.avatar;
          img.alt = c.name;
          d.appendChild(img);
      } else {
          d.textContent = c.initial;
      }
      return d;
  }

  function buildConvItem(c) {
    const a = el('a', 'conv');
    a.href = c.url;
    a.dataset.id = c.id;
    if (c.id === activeId) a.classList.add('active');

    a.appendChild(avatarEl(c));

    const main = el('div', 'conv-main');
    const top = el('div', 'conv-top');
    top.appendChild(el('span', 'conv-name', c.name));
    const time = el('time', 'conv-time' + (c.unread > 0 ? ' unread' : ''),
      c.has_messages ? listTime(new Date(c.last_at)) : '');
    top.appendChild(time);

    const bottom = el('div', 'conv-bottom');
    if (typingTimers.has(c.id)) {
      bottom.appendChild(el('span', 'conv-preview is-typing', 'typing…'));
    } else if (!c.has_messages) {
      bottom.appendChild(el('span', 'conv-preview muted-italic', 'Say hi 👋'));
    } else {
      bottom.appendChild(el('span', 'conv-preview', (c.last_mine ? 'You: ' : '') + c.preview));
    }
    if (c.unread > 0) bottom.appendChild(el('span', 'badge', c.unread > 99 ? '99+' : String(c.unread)));

    main.appendChild(top);
    main.appendChild(bottom);
    a.appendChild(main);
    return a;
  }

  function renderSidebar() {
    const q = els.search ? els.search.value.trim().toLowerCase() : '';
    const items = Array.from(convs.values())
      .sort((a, b) => new Date(b.last_at) - new Date(a.last_at))
      .filter((c) => !q || c.name.toLowerCase().includes(q));
    els.list.replaceChildren(...items.map(buildConvItem));
    els.empty.hidden = convs.size > 0;

    let unread = 0;
    convs.forEach((c) => { unread += c.unread || 0; });
    document.title = (unread ? '(' + unread + ') ' : '') + TITLE;
  }

  if (els.search) els.search.addEventListener('input', renderSidebar);

  function refreshSidebar() {
    return fetch(cfg.urls.conversations, { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((data) => {
        convs.clear();
        data.conversations.forEach((c) => convs.set(c.id, c));
        if (activeId && convs.has(activeId)) convs.get(activeId).unread = 0;
        renderSidebar();
      })
      .catch(() => {});
  }

  function markTyping(id) {
    clearTimeout(typingTimers.get(id));
    typingTimers.set(id, setTimeout(() => clearTyping(id), 3500));
    if (id === activeId && els.peerStatus) els.peerStatus.hidden = false;
    renderSidebar();
  }

  function clearTyping(id) {
    if (!typingTimers.has(id)) return;
    clearTimeout(typingTimers.get(id));
    typingTimers.delete(id);
    if (id === activeId && els.peerStatus) els.peerStatus.hidden = true;
    renderSidebar();
  }

  // ------------------------------------------------------------ open conversation
  let store = [];                          // confirmed messages, ascending by id
  const pending = new Map();               // client_id -> {body, el, created_at}
  let lastDay = null;
  let hasMore = !!cfg.hasMore;

  function nearBottom() {
    const s = els.scroller;
    return s.scrollHeight - s.scrollTop - s.clientHeight < 140;
  }

  function scrollToBottom() {
    els.scroller.scrollTop = els.scroller.scrollHeight;
  }

  function setTicks(node, state) {
    const t = node.querySelector('.ticks');
    if (t) t.dataset.state = state;
  }

  function buildMessageEl(m, pendingState) {
    const mine = m.sender === ME;
    const row = el('div', 'msg ' + (mine ? 'out' : 'in'));
    if (m.id) row.dataset.id = m.id;
    const bubble = el('div', 'bubble');
    if (m.kind === 'image' && m.file) {
      const a = el('a', 'media-link');
      a.href = m.file; a.target = '_blank'; a.rel = 'noopener';
      const img = document.createElement('img');
      img.className = 'chat-img'; img.src = m.file; img.alt = 'Photo'; img.loading = 'lazy';
      img.addEventListener('load', () => {
        const s = els.scroller;
        if (s.scrollHeight - s.scrollTop - s.clientHeight < 500) scrollToBottom();
      });
      a.appendChild(img);
      bubble.appendChild(a);

    } else if (m.kind === 'voice' && m.file) {
      const audio = document.createElement('audio');
      audio.className = 'chat-audio'; audio.controls = true; audio.preload = 'metadata'; audio.src = m.file;
      bubble.appendChild(audio);
    }
    if (m.body) bubble.appendChild(el('span', 'text', m.body));
    const meta = el('span', 'meta');
    meta.appendChild(el('time', null, clock(new Date(m.created_at))));
    if (mine) {
      const ticks = el('span', 'ticks');
      ticks.dataset.state = pendingState ? 'pending' : (m.read ? 'read' : 'sent');
      meta.appendChild(ticks);
    }
    bubble.appendChild(meta);
    row.appendChild(bubble);
    return row;
  }

  function appendDaySeparator(date) {
    if (lastDay && sameDay(lastDay, date)) return;
    lastDay = date;
    els.inner.appendChild(el('div', 'day-chip', dayLabel(date)));
  }

  function appendMessageEl(m) {
    appendDaySeparator(new Date(m.created_at));
    els.inner.appendChild(buildMessageEl(m, false));
  }

  function renderAll() {
    els.inner.replaceChildren();
    lastDay = null;
    store.forEach(appendMessageEl);
    pending.forEach((p) => {
      appendDaySeparator(new Date(p.created_at));
      els.inner.appendChild(p.el);
    });
    els.loadMore.hidden = !hasMore;
  }

  function addConfirmed(m, forceStick) {
    if (store.some((x) => x.id === m.id)) return false;
    const stick = forceStick || nearBottom() || m.sender === ME;

    // Our own message coming back from the server: drop the pending bubble.
    if (m.client_id && pending.has(m.client_id)) {
      pending.get(m.client_id).el.remove();
      pending.delete(m.client_id);
    }

    const last = store.length ? store[store.length - 1] : null;
    store.push(m);
    if (last && m.id < last.id) {               // arrived out of order: rebuild
      store.sort((a, b) => a.id - b.id);
      renderAll();
    } else {
      appendMessageEl(m);
    }
    if (stick) scrollToBottom();
    return true;
  }

  function applyReadReceipt(upTo) {
    store.forEach((m) => {
      if (m.sender === ME && m.id <= upTo) {
        m.read = true;
        const row = els.inner.querySelector('[data-id="' + m.id + '"]');
        if (row) setTicks(row, 'read');
      }
    });
  }

  function lastId() {
    return store.length ? store[store.length - 1].id : 0;
  }

  function loadEarlier() {
    if (!store.length) return;
    els.loadMore.disabled = true;
    fetch(cfg.urls.messages + '?before=' + store[0].id, { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((data) => {
        const prevHeight = els.scroller.scrollHeight;
        const prevTop = els.scroller.scrollTop;
        store = data.messages.concat(store);
        hasMore = data.has_more;
        renderAll();
        els.scroller.scrollTop = prevTop + (els.scroller.scrollHeight - prevHeight);
      })
      .catch(() => toast('Could not load earlier messages.'))
      .finally(() => { els.loadMore.disabled = false; });
  }

  function syncMissed() {
    if (!activeId) return Promise.resolve();
    return fetch(cfg.urls.messages + '?after=' + lastId(), { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((data) => {
        let changed = false;
        data.messages.forEach((m) => { if (addConfirmed(m)) changed = true; });
        if (changed) sendRead();
      })
      .catch(() => {});
  }

  // --------------------------------------------------------------- websocket
  let ws = null;
  let retries = 0;
  let everConnected = false;
  let pingTimer = null;
  let reconnectTimer = null;
  let bannerTimer = null;
  let lastTypingSent = 0;

  function isOpen() { return ws && ws.readyState === WebSocket.OPEN; }

  function wsSend(obj) {
    if (isOpen()) { ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  function showBanner(text) {
    if (els.banner) { els.banner.textContent = text; els.banner.hidden = false; }
  }

  function hideBanner() {
    clearTimeout(bannerTimer);
    if (els.banner) els.banner.hidden = true;
  }

  function connect() {
    clearTimeout(reconnectTimer);
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    clearTimeout(bannerTimer);
    bannerTimer = setTimeout(() => showBanner(everConnected ? 'Reconnecting…' : 'Connecting…'), 1500);

    const scheme = location.protocol === 'https:' ? 'wss://' : 'ws://';
    ws = new WebSocket(scheme + location.host + cfg.urls.ws);

    ws.onopen = () => {
      retries = 0;
      hideBanner();
      clearInterval(pingTimer);
      pingTimer = setInterval(() => wsSend({ type: 'ping' }), 25000);
      const reconnected = everConnected;
      everConnected = true;
      if (reconnected) { refreshSidebar(); syncMissed(); }
      flushPending();
      sendRead();
    };

    ws.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      handleEvent(data);
    };

    ws.onclose = (event) => {
      clearInterval(pingTimer);
      if (event.code === 4401) { location.href = '/login/'; return; }   // session expired
      bannerTimer = setTimeout(() => showBanner('Reconnecting…'), 800);
      const delay = Math.min(1000 * Math.pow(2, retries), 15000);
      retries += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    ws.onerror = () => { try { ws.close(); } catch (e) { /* ignore */ } };
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case 'message': return onMessage(ev);
      case 'typing': return markTyping(ev.conversation);
      case 'read':
        if (ev.conversation === activeId) applyReadReceipt(ev.up_to);
        return;
      case 'read_self': {
        const c = convs.get(ev.conversation);
        if (c && c.unread) { c.unread = 0; renderSidebar(); }
        return;
      }
      case 'conversation': {
        const info = ev.conversation;
        if (!convs.has(info.id)) {
          convs.set(info.id, Object.assign({}, info, {
            preview: '', last_mine: false, last_at: new Date().toISOString(), has_messages: false, unread: 0,
          }));
          renderSidebar();
          toast(info.name + ' joined through your invite link 🎉');
        }
        return;
      }
      case 'limit': return onLimit(ev);
      case 'error': return toast(ev.detail || 'Something went wrong.');
      default: return;
    }
  }

  // The server refused a text message because today's free limit (and any bought messages) ran out.
  function onLimit(ev) {
    renderQuota(ev.quota);
    const p = ev.client_id ? pending.get(ev.client_id) : null;
    if (p) {
      p.el.remove();
      pending.delete(ev.client_id);
      if (els.input && !els.input.value.trim()) {      // give the text back so it isn't lost
        els.input.value = p.body;
        autoGrow();
        updateComposerButtons();
      }
    }
    limitToast(ev.detail);
  }

  function onMessage(ev) {
    if (ev.quota) renderQuota(ev.quota);
    const info = ev.conversation;
    const m = ev.message;
    let c = convs.get(info.id);
    if (!c) {
      c = Object.assign({}, info, { preview: '', last_mine: false, last_at: m.created_at, has_messages: true, unread: 0 });
      convs.set(info.id, c);
    }
    c.preview = previewMsg(m);
    c.last_mine = m.sender === ME;
    c.last_at = m.created_at;
    c.has_messages = true;

    const incoming = m.sender !== ME;
    const isActive = info.id === activeId;
    if (incoming) clearTyping(info.id);

    if (isActive) {
      addConfirmed(m);
      if (incoming) {
        if (document.visibilityState === 'visible') sendRead();
        else c.unread = (c.unread || 0) + 1;
      }
    } else if (incoming) {
      c.unread = (c.unread || 0) + 1;
    }
    renderSidebar();
  }

  function sendRead() {
    if (!activeId || document.visibilityState !== 'visible') return;
    if (wsSend({ type: 'read', conversation: activeId })) {
      const c = convs.get(activeId);
      if (c && c.unread) { c.unread = 0; renderSidebar(); }
    }
  }

  // ----------------------------------------------------------------- sending
  function flushPending() {
    pending.forEach((p, clientId) => {
      wsSend({ type: 'message', conversation: activeId, body: p.body, client_id: clientId });
    });
  }

  function send() {
    const body = els.input.value.trim();
    if (!body || !activeId) return;

    const clientId = uuid();
    const createdAt = new Date().toISOString();
    const node = buildMessageEl({ sender: ME, body: body, created_at: createdAt }, true);
    pending.set(clientId, { body: body, el: node, created_at: createdAt });
    appendDaySeparator(new Date(createdAt));
    els.inner.appendChild(node);
    scrollToBottom();

    wsSend({ type: 'message', conversation: activeId, body: body, client_id: clientId });
    // If the socket is down the message stays "pending" and is sent on reconnect.

    els.input.value = '';
    autoGrow();
    updateComposerButtons();
    els.input.focus();
  }

    // -------------------------------------------------------- photos & voice notes
  function csrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function uploadFile(blob, kind, filename, caption) {
    if (!cfg.urls.attach) return Promise.resolve();
    const fd = new FormData();
    fd.append('file', blob, filename);
    fd.append('kind', kind);
    fd.append('client_id', uuid());
    if (caption) fd.append('caption', caption);
    els.form.classList.add('busy');
    return fetch(cfg.urls.attach, {
      method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': csrfToken() },
    })
      .then((r) => r.json().catch(() => ({})).then((d) => {
        if (d.quota) renderQuota(d.quota);
        if (r.status === 402) { limitToast(d.error); return false; }   // daily limit reached
        if (!r.ok) throw new Error(d.error || 'Could not send.');
        return true;
      }))
      .catch((e) => { toast(e.message || 'Could not send. Check your connection.'); return false; })
      .finally(() => els.form.classList.remove('busy'));
  }

  // Shrink big phone photos before upload (max 1600px, JPEG) so they send fast.
  function shrinkImage(file) {
    if (file.type === 'image/gif' || !window.createImageBitmap) return Promise.resolve(file);
    return createImageBitmap(file).then((bmp) => {
      const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(bmp.width * scale);
      canvas.height = Math.round(bmp.height * scale);
      canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
      return new Promise((resolve) => canvas.toBlob((b) => resolve(b || file), 'image/jpeg', 0.85));
    }).catch(() => file);
  }

  function sendPhoto(file) {
    if (!file) return;
    if (!file.type.startsWith('image/')) { toast('Please choose an image.'); return; }
    shrinkImage(file).then((blob) => uploadFile(blob, 'image', 'photo.jpg', els.input.value.trim()))
      .then((ok) => { if (ok) { els.input.value = ''; autoGrow(); updateComposerButtons(); } });
  }

  // Voice recording (MediaRecorder; needs https or localhost for the microphone).
  const MAX_REC_SECONDS = 180;
  let rec = null, recChunks = [], recStream = null, recStart = 0, recTick = null, recCancelled = false;

  function pickAudioType() {
    const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
    return options.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || '';
  }

  function fmtSecs(s) { return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }

  function startRecording() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      toast('Voice messages are not supported in this browser (use https).'); return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      recStream = stream;
      const mime = pickAudioType();
      rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recChunks = []; recCancelled = false;
      rec.ondataavailable = (e) => { if (e.data && e.data.size) recChunks.push(e.data); };
      rec.onstop = () => {
        recStream.getTracks().forEach((t) => t.stop());
        clearInterval(recTick);
        els.form.classList.remove('recording');
        els.recBar.hidden = true;
        if (recCancelled) return;
        if (Date.now() - recStart < 600) { toast('Too short — hold the recording a bit longer.'); return; }
        const type = rec.mimeType || mime || 'audio/webm';
        const ext = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm';
        uploadFile(new Blob(recChunks, { type: type }), 'voice', 'voice.' + ext);
      };
      rec.start();
      recStart = Date.now();
      els.recTime.textContent = '0:00';
      els.recBar.hidden = false;
      els.form.classList.add('recording');
      recTick = setInterval(() => {
        const secs = Math.floor((Date.now() - recStart) / 1000);
        els.recTime.textContent = fmtSecs(secs);
        if (secs >= MAX_REC_SECONDS) stopRecording(false);
      }, 250);
    }).catch(() => toast('Microphone access was blocked. Allow it in your browser settings.'));
  }

  function stopRecording(cancel) {
    if (!rec || rec.state === 'inactive') return;
    recCancelled = !!cancel;
    rec.stop();
  }

  function updateComposerButtons() {
    const hasText = els.input.value.trim().length > 0;
    els.sendBtn.hidden = !hasText;
    els.micBtn.hidden = hasText;
  }

  function autoGrow() {
    els.input.style.height = 'auto';
    els.input.style.height = Math.min(els.input.scrollHeight, 140) + 'px';
  }

  // -------------------------------------------------------------------- init
  renderSidebar();
  renderQuota(cfg.quota);

  if (active) {
    els.peerAvatar.replaceWith(avatarEl(active));
    document.getElementById('peer-link').href = active.profile_url;
    els.peerName.textContent = active.name;

    store = cfg.messages.slice();
    renderAll();
    scrollToBottom();

    els.loadMore.addEventListener('click', loadEarlier);
    els.form.addEventListener('submit', (e) => { e.preventDefault(); send(); });
    els.photoInput.addEventListener('change', () => {
      sendPhoto(els.photoInput.files[0]);
      els.photoInput.value = '';
    });
    els.micBtn.addEventListener('click', startRecording);
    $('#rec-cancel').addEventListener('click', () => stopRecording(true));
    $('#rec-send').addEventListener('click', () => stopRecording(false));
    updateComposerButtons();

    els.input.addEventListener('input', () => {
      autoGrow();
      updateComposerButtons();
      const now = Date.now();
      if (els.input.value && now - lastTypingSent > 2500) {
        lastTypingSent = now;
        wsSend({ type: 'typing', conversation: activeId });
      }
    });

    els.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !isTouch && !e.isComposing) {
        e.preventDefault();
        send();
      }
    });

    if (!isTouch) els.input.focus();
    window.addEventListener('resize', () => { if (nearBottom()) scrollToBottom(); });
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      if (!isOpen()) { retries = 0; connect(); }
      sendRead();
    }
  });
  window.addEventListener('online', () => { retries = 0; connect(); });

  connect();
})();
