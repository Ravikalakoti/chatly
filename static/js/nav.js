// Account dropdown: close on outside click / Escape; highlight the in-page tab (Discover / Invite) from the URL hash.
(function () {
  var menu = document.querySelector('.user-menu');
  if (menu) {
    document.addEventListener('click', function (e) { if (!menu.contains(e.target)) menu.removeAttribute('open'); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') menu.removeAttribute('open'); });
  }
  // On the home page, mark Discover / Invite as active while the visitor is on those sections.
  var links = document.querySelectorAll('.topnav a[href*="#"], .tabbar a[href*="#"]');
  if (!links.length || !('IntersectionObserver' in window)) return;
  var map = { discover: 'discover', invite: 'invite' };
  Object.keys(map).forEach(function (id) {
    var sec = document.getElementById(id);
    if (!sec) return;
    new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        document.querySelectorAll('.topnav a, .tabbar a:not(.tab-main)').forEach(function (a) { a.classList.remove('on'); });
        document.querySelectorAll('.topnav a[href$="#' + id + '"], .tabbar a[href$="#' + id + '"]').forEach(function (a) { a.classList.add('on'); });
      });
    }, { rootMargin: '-35% 0px -55% 0px' }).observe(sec);
  });
})();
