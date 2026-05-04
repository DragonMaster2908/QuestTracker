self.addEventListener('push', function(event) {
    const data = event.data ? event.data.json() : { title: 'Quest Alert', body: 'Time to check your tasks!' };
    
    const options = {
        body: data.body,
        icon: 'https://cdn-icons-png.flaticon.com/512/536/536034.png',
        badge: 'https://cdn-icons-png.flaticon.com/512/536/536034.png',
        vibrate: [100, 50, 100],
        data: { url: '/' }
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    event.waitUntil(clients.openWindow('/'));
});
