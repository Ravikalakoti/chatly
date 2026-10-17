(function () {
  'use strict';

  var input = document.getElementById('invite-link');
  var copyBtn = document.getElementById('copy-btn');
  var shareBtn = document.getElementById('share-btn');
  if (!input || !copyBtn) return;

  function flash(label) {
    var original = 'Copy link';
    copyBtn.textContent = label;
    setTimeout(function () { copyBtn.textContent = original; }, 2000);
  }

  function fallbackCopy() {
    input.focus();
    input.select();
    input.setSelectionRange(0, input.value.length);
    try {
      return document.execCommand('copy');
    } catch (e) {
      return false;
    }
  }

  copyBtn.addEventListener('click', function () {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(input.value).then(
        function () { flash('Copied ✓'); },
        function () { flash(fallbackCopy() ? 'Copied ✓' : 'Press Ctrl+C'); }
      );
    } else {
      flash(fallbackCopy() ? 'Copied ✓' : 'Press Ctrl+C');
    }
  });

  input.addEventListener('focus', function () { input.select(); });

  // Native share sheet on phones (WhatsApp, SMS, Gmail, ...) when the browser supports it.
  if (navigator.share) {
    shareBtn.hidden = false;
    shareBtn.addEventListener('click', function () {
      navigator.share({
        title: 'Chat with me on Chatly',
        text: 'Join me on Chatly:',
        url: input.value
      }).catch(function () { /* user cancelled */ });
    });
  }
})();
