(function () {
    const dataEl = document.getElementById('map-points-data');
    if (!dataEl) return;

    const points = JSON.parse(dataEl.textContent || '[]').filter(
        point =>
            point &&
            point.status_key === 'pending' &&
            Number.isFinite(Number(point.lat)) &&
            Number.isFinite(Number(point.lng))
    );
    const emptyState = document.getElementById('mapEmptyState');
    const markersLayer = L.layerGroup();
    // Bayawan City center
    const DEFAULT_CENTER = [9.3668, 122.8055];
    const DEFAULT_ZOOM = 13;
    let isInitialRender = true;

    const map = L.map('requests-map');
    const mapEl = document.getElementById('requests-map');

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    markersLayer.addTo(map);

    function mapToDefaultView() {
        map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    }

    // Keep marker size readable per zoom level (smaller on zoom-out).
    function markerScaleForZoom(zoom) {
        if (zoom <= 10) return 0.62;
        if (zoom <= 11) return 0.72;
        if (zoom <= 12) return 0.82;
        if (zoom <= 13) return 0.92;
        if (zoom <= 14) return 1;
        return 1.06;
    }

    function applyMarkerScale() {
        if (!mapEl) return;
        const scale = markerScaleForZoom(map.getZoom());
        mapEl.style.setProperty('--request-marker-scale', String(scale));
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function requestTypeClass(point) {
        return point.request_type_key === 'surrender'
            ? 'request-map-marker--surrender'
            : 'request-map-marker--capture';
    }

    function requestTypeBadge(point) {
        return point.request_type_key === 'surrender'
            ? '<span class="request-map-marker-badge" aria-hidden="true">S</span>'
            : '<span class="request-map-marker-badge" aria-hidden="true">C</span>';
    }

    function markerIconHtml(point) {
        const avatarUrl = escapeHtml(point.profile_image_url || point.image_url || '');
        const typeClass = requestTypeClass(point);

        return `
            <div class="request-map-marker ${typeClass}">
                ${
                    avatarUrl
                        ? `<img src="${avatarUrl}" alt="${escapeHtml(point.requester_name || point.user)} profile">`
                        : `<span class="request-map-marker-fallback">${escapeHtml((point.user || '?').charAt(0).toUpperCase())}</span>`
                }
                ${requestTypeBadge(point)}
            </div>
        `;
    }

    function popupHtml(point) {
        const typeClass = point.request_type_key === 'surrender'
            ? 'request-popup-pill request-popup-pill--surrender'
            : 'request-popup-pill request-popup-pill--capture';
        const requestImage = point.image_url
            ? `<div class="request-popup-proof"><img src="${escapeHtml(point.image_url)}" alt="${escapeHtml(point.request_type_label)} proof"></div>`
            : '';
        const requesterName = escapeHtml(point.requester_name || point.user);
        const username = escapeHtml(point.user);
        const submission = escapeHtml(point.submission_type_label || 'Not specified');
        const location = escapeHtml(point.location_label || 'Pinned location');
        const phone = escapeHtml(point.requester_phone || 'No phone number');
        const address = escapeHtml(point.requester_address || 'No address provided');
        const reason = escapeHtml(point.reason || 'Not specified');
        const createdAt = escapeHtml(point.created_at || '');

        return `
            <div class="request-popup-card">
                <div class="request-popup-header">
                    <img class="request-popup-avatar" src="${escapeHtml(point.profile_image_url || point.image_url || '')}" alt="${requesterName} profile">
                    <div class="request-popup-title-block">
                        <strong>${requesterName}</strong>
                        <span>@${username}</span>
                    </div>
                </div>
                <div class="${typeClass}">${escapeHtml(point.request_type_label || 'Request')}</div>
                <div class="request-popup-row"><strong>Status:</strong> ${escapeHtml(point.status || 'Pending')}</div>
                <div class="request-popup-row"><strong>Submission:</strong> ${submission}</div>
                <div class="request-popup-row"><strong>Location:</strong> ${location}</div>
                <div class="request-popup-row"><strong>Phone:</strong> ${phone}</div>
                <div class="request-popup-row"><strong>Address:</strong> ${address}</div>
                <div class="request-popup-row"><strong>Reason:</strong> ${reason}</div>
                <div class="request-popup-row"><strong>Submitted:</strong> ${createdAt}</div>
                ${requestImage}
            </div>
        `;
    }

    function renderMarkers() {
        markersLayer.clearLayers();
        const visible = points;

        if (!visible.length) {
            emptyState.style.display = 'block';
            mapToDefaultView();
            return;
        }
        emptyState.style.display = 'none';

        const bounds = [];
        visible.forEach(point => {
            const marker = L.marker([point.lat, point.lng], {
                icon: L.divIcon({
                    className: 'request-map-marker-wrap',
                    html: markerIconHtml(point),
                    iconSize: [42, 42],
                    iconAnchor: [21, 21],
                    popupAnchor: [0, -18],
                }),
            }).bindPopup(popupHtml(point), { className: 'map-popup' });

            marker.addTo(markersLayer);
            bounds.push([point.lat, point.lng]);
        });

        if (isInitialRender) {
            mapToDefaultView();
            isInitialRender = false;
            applyMarkerScale();
            return;
        }

        if (bounds.length === 1) {
            map.setView(bounds[0], 13);
        } else {
            map.fitBounds(bounds, { padding: [30, 30], maxZoom: 13 });
        }
    }

    map.on('zoomend', applyMarkerScale);
    mapToDefaultView();
    applyMarkerScale();
    renderMarkers();
})();


(function () {
    const tabs = document.querySelectorAll('.tab-btn');
    const panels = document.querySelectorAll('.tab-panel');

    function activate(tabName) {
        tabs.forEach(btn => {
            const active = btn.dataset.tab === tabName;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        panels.forEach(panel => {
            panel.classList.toggle('is-active', panel.dataset.panel === tabName);
        });
    }

    tabs.forEach(btn => {
        btn.addEventListener('click', () => activate(btn.dataset.tab));
    });
})();
