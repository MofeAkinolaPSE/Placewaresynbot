/* ACE service worker: shows phone / desktop notifications (Web Push) and opens ACE on the right page when one
   is tapped. It does not cache pages - ACE always loads fresh from the server. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: "ACE", body: event.data ? event.data.text() : "" }; }
  const title = data.title || "ACE";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: data.tag || undefined,
    renotify: !!data.tag,
    data: { url: data.url || "#/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const hash = (event.notification.data && event.notification.data.url) || "#/";
  const target = new URL("/" + (hash.startsWith("#") ? hash : "#" + hash), self.location.origin).href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      if (new URL(w.url).origin === self.location.origin) {
        await w.focus();
        try { await w.navigate(target); } catch (e) { w.postMessage({ type: "ace:navigate", url: hash }); }
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
