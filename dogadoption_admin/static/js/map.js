(function () {
    const dataEl = document.getElementById('map-points-data');
    if (!dataEl) return;

    const points = JSON.parse(dataEl.textContent || '[]');
    const acceptedPoints = points.filter(p => p.status_key === 'accepted');
    const dateFilter = document.getElementById('mapDateFilter');
    const clearDateFilter = document.getElementById('clearDateFilter');
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

    function filteredPoints() {
        const selectedDate = dateFilter?.value || '';
        if (!selectedDate) return acceptedPoints;
        return acceptedPoints.filter(
            p => p.scheduled_date_iso && p.scheduled_date_iso === selectedDate
        );
    }

    function groupByBarangay(pointsList) {
        const grouped = new Map();
        pointsList.forEach(point => {
            const barangay = (point.barangay || '').trim();
            const key = barangay ? barangay.toLowerCase() : `request-${point.id}`;
            if (!grouped.has(key)) {
                // One marker per barangay with request count shown in popup.
                grouped.set(key, {
                    barangay_label: point.location_label || 'Pinned location',
                    lat: point.lat,
                    lng: point.lng,
                    requests: [],
                });
            }
            grouped.get(key).requests.push(point);
        });
        return Array.from(grouped.values());
    }

    function renderMarkers() {
        markersLayer.clearLayers();
        const visible = groupByBarangay(filteredPoints());

        if (!visible.length) {
            emptyState.style.display = 'block';
            mapToDefaultView();
            return;
        }
        emptyState.style.display = 'none';

        const bounds = [];
        visible.forEach(group => {
            const sample = group.requests[0];
            const markerImage = sample.image_url || '';
            const scheduleLabel = sample.scheduled_date_display || 'Not set';
            const popupRows = group.requests
                .slice(0, 5)
                .map(item => `#${item.id} - ${item.user}`)
                .join('<br>');
            const remaining = group.requests.length - 5;

            const popup = [
                `<strong>${group.barangay_label}</strong>`,
                `Accepted requests: ${group.requests.length}`,
                `Scheduled date: ${scheduleLabel}`,
                popupRows,
                remaining > 0 ? `+${remaining} more request(s)` : '',
            ].join('<br>');

            const markerIconHtml = markerImage
                ? `<div class="request-map-marker has-image"><img src="${escapeHtml(markerImage)}" alt="Request image"></div>`
                : '<div class="request-map-marker"></div>';

            // Use image-based marker design with green fallback marker.
            const marker = L.marker([group.lat, group.lng], {
                icon: L.divIcon({
                    className: 'request-map-marker-wrap',
                    html: markerIconHtml,
                    iconSize: [30, 30],
                    iconAnchor: [15, 15],
                    popupAnchor: [0, -14],
                }),
            }).bindPopup(popup, { className: 'map-popup' });

            marker.addTo(markersLayer);
            bounds.push([group.lat, group.lng]);
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

    dateFilter?.addEventListener('change', renderMarkers);
    clearDateFilter?.addEventListener('click', () => {
        if (dateFilter) dateFilter.value = '';
        renderMarkers();
    });

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
