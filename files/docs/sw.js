/* 离线缓存：页面外壳缓存优先；data/ 网络优先、断网时用缓存（可离线读最近看过的简报）。 */
var CACHE = "pb-shell-2.1.0";
var SHELL = ["./", "index.html", "style.css?v=2.1.0", "app.js?v=2.1.0", "manage.js?v=2.1.0", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k.indexOf("pb-") === 0 && k !== CACHE && k !== "pb-data"; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  // 只处理本站 GET；GitHub 接口（api.github.com）不经过缓存
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.indexOf("/data/") >= 0) {
    var key = url.origin + url.pathname; // 去掉 ?t= 参数作为缓存键
    e.respondWith(fetch(e.request).then(function (r) {
      var copy = r.clone(); caches.open("pb-data").then(function (c) { c.put(key, copy); }); return r;
    }).catch(function () { return caches.match(key); }));
    return;
  }
  e.respondWith(caches.match(e.request).then(function (r) { return r || fetch(e.request); }));
});
