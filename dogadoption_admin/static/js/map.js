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

(function () {
    function parseJsonScript(id) {
        const node = document.getElementById(id);
        if (!node) return [];
        try {
            return JSON.parse(node.textContent || '[]');
        } catch (e) {
            return [];
        }
    }

    function initSingleSelectCalendar(config) {
        const availableDates = parseJsonScript('accepted-calendar-dates-data');
        const availableSet = new Set(availableDates);
        const daysContainer = document.getElementById(config.daysId);
        const weekdaysContainer = document.getElementById(config.weekdaysId);
        const monthLabel = document.getElementById(config.monthLabelId);
        const prevBtn = document.getElementById(config.prevId);
        const nextBtn = document.getElementById(config.nextId);
        const hiddenInput = document.getElementById(config.inputId);
        const statusEl = document.getElementById(config.statusId);
        const onSelect = typeof config.onSelect === 'function' ? config.onSelect : null;

        if (!daysContainer || !weekdaysContainer || !monthLabel || !prevBtn || !nextBtn || !hiddenInput) {
            return null;
        }

        const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        let selectedDate = hiddenInput.value || '';
        let currentMonth = (() => {
            const anchor = selectedDate || availableDates[0] || '';
            if (anchor) {
                const [year, month] = anchor.split('-').map(Number);
                return new Date(year, (month || 1) - 1, 1);
            }
            return new Date(today.getFullYear(), today.getMonth(), 1);
        })();

        function formatIso(dateObj) {
            const year = dateObj.getFullYear();
            const month = String(dateObj.getMonth() + 1).padStart(2, '0');
            const day = String(dateObj.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        }

        function renderStatus() {
            if (!statusEl) return;
            if (!selectedDate) {
                statusEl.textContent = config.emptyLabel || 'No date selected yet.';
                return;
            }
            const selectedObj = new Date(`${selectedDate}T00:00:00`);
            statusEl.textContent = `${config.selectedPrefix || 'Selected date'}: ${selectedObj.toLocaleDateString(undefined, {
                month: 'short',
                day: '2-digit',
                year: 'numeric',
            })}`;
        }

        weekdaysContainer.innerHTML = weekdays
            .map((day) => `<div class="weekday">${day}</div>`)
            .join('');

        function renderMonth() {
            const year = currentMonth.getFullYear();
            const month = currentMonth.getMonth();
            const firstDay = new Date(year, month, 1);
            const startWeekday = firstDay.getDay();
            const daysInMonth = new Date(year, month + 1, 0).getDate();

            monthLabel.textContent = currentMonth.toLocaleDateString(undefined, {
                month: 'long',
                year: 'numeric',
            });

            let html = '';
            for (let i = 0; i < startWeekday; i++) {
                html += '<button type="button" class="day-cell empty" disabled></button>';
            }

            for (let day = 1; day <= daysInMonth; day++) {
                const dateObj = new Date(year, month, day);
                dateObj.setHours(0, 0, 0, 0);
                const iso = formatIso(dateObj);
                const isPast = dateObj < today;
                const isAvailable = availableSet.has(iso);
                const isSelected = selectedDate && iso === selectedDate;
                const classes = [
                    'day-cell',
                    isAvailable ? 'available' : '',
                    isSelected ? 'selected' : '',
                    !isAvailable || isPast ? 'disabled' : '',
                ].join(' ').trim();

                html += `<button type="button" class="${classes}" data-date="${iso}" ${!isAvailable || isPast ? 'disabled' : ''}>${day}</button>`;
            }

            daysContainer.innerHTML = html;
            daysContainer.querySelectorAll('.day-cell[data-date]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    selectedDate = btn.getAttribute('data-date') || '';
                    hiddenInput.value = selectedDate;
                    renderStatus();
                    renderMonth();
                    if (onSelect) onSelect(selectedDate);
                });
            });
        }

        prevBtn.addEventListener('click', () => {
            currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1);
            renderMonth();
        });

        nextBtn.addEventListener('click', () => {
            currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1);
            renderMonth();
        });

        renderStatus();
        renderMonth();

        return {
            setDate(dateValue) {
                selectedDate = dateValue || '';
                hiddenInput.value = selectedDate;
                if (selectedDate) {
                    const [year, month] = selectedDate.split('-').map(Number);
                    currentMonth = new Date(year, (month || 1) - 1, 1);
                }
                renderStatus();
                renderMonth();
            },
        };
    }

    const acceptedSelectAll = document.getElementById('accepted_select_all');
    const acceptedCheckboxes = Array.from(document.querySelectorAll('.accepted-row-checkbox'));
    const bulkMarkDoneButton = document.getElementById('bulkMarkDoneButton');
    const bulkUpdateButton = document.getElementById('bulkUpdateButton');

    function syncBulkActionState() {
        const selectedCount = acceptedCheckboxes.filter((item) => item.checked).length;
        const hasSelection = selectedCount > 0;
        if (bulkMarkDoneButton) bulkMarkDoneButton.disabled = !hasSelection;
        if (bulkUpdateButton) bulkUpdateButton.disabled = !hasSelection;
    }

    if (acceptedSelectAll && acceptedCheckboxes.length) {
        acceptedSelectAll.addEventListener('change', () => {
            acceptedCheckboxes.forEach((checkbox) => {
                checkbox.checked = acceptedSelectAll.checked;
            });
            syncBulkActionState();
        });

        acceptedCheckboxes.forEach((checkbox) => {
            checkbox.addEventListener('change', () => {
                acceptedSelectAll.checked = acceptedCheckboxes.every((item) => item.checked);
                syncBulkActionState();
            });
        });

        syncBulkActionState();
    }

    const acceptedCalendarPanel = document.getElementById('acceptedCalendarPanel');
    const acceptedCalendarToggle = document.getElementById('acceptedCalendarToggle');
    const acceptedCalendarForm = document.getElementById('acceptedCalendarFilterForm');
    initSingleSelectCalendar({
        daysId: 'accepted_days',
        weekdaysId: 'accepted_weekdays',
        monthLabelId: 'accepted_month_label',
        prevId: 'accepted_calendar_prev',
        nextId: 'accepted_calendar_next',
        inputId: 'accepted_calendar_date_input',
        onSelect() {
            if (acceptedCalendarForm) acceptedCalendarForm.submit();
        },
    });

    acceptedCalendarToggle?.addEventListener('click', () => {
        if (!acceptedCalendarPanel) return;
        acceptedCalendarPanel.hidden = !acceptedCalendarPanel.hidden;
    });

    const rescheduleModalEl = document.getElementById('rescheduleRequestModal');
    const rescheduleActionInput = document.getElementById('reschedule_action_input');
    const rescheduleRequestId = document.getElementById('reschedule_request_id');
    const rescheduleRequestTitle = document.getElementById('reschedule_request_title');
    const rescheduleSelectedIdsContainer = document.getElementById('reschedule_selected_ids_container');
    const bulkRescheduleButton = document.querySelector('.js-open-bulk-reschedule');
    const rescheduleCalendar = initSingleSelectCalendar({
        daysId: 'reschedule_days',
        weekdaysId: 'reschedule_weekdays',
        monthLabelId: 'reschedule_month_label',
        prevId: 'reschedule_calendar_prev',
        nextId: 'reschedule_calendar_next',
        inputId: 'reschedule_date_input',
        statusId: 'reschedule_selection_status',
        emptyLabel: 'No new date selected yet.',
        selectedPrefix: 'Selected new schedule',
    });

    function resetRescheduleSelectionIds() {
        if (rescheduleSelectedIdsContainer) {
            rescheduleSelectedIdsContainer.innerHTML = '';
        }
    }

    function appendSelectedRequestIds(ids) {
        if (!rescheduleSelectedIdsContainer) return;
        resetRescheduleSelectionIds();
        ids.forEach((idValue) => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'selected_request_ids';
            input.value = String(idValue);
            rescheduleSelectedIdsContainer.appendChild(input);
        });
    }

    document.querySelectorAll('.js-open-reschedule').forEach((button) => {
        button.addEventListener('click', () => {
            if (!rescheduleModalEl || !window.bootstrap || !window.bootstrap.Modal) return;
            const requestId = button.getAttribute('data-request-id') || '';
            const requesterName = button.getAttribute('data-requester-name') || 'this request';
            const currentDate = button.getAttribute('data-current-date') || '';
            if (rescheduleActionInput) rescheduleActionInput.value = 'reschedule_single';
            if (rescheduleRequestId) rescheduleRequestId.value = requestId;
            resetRescheduleSelectionIds();
            if (rescheduleRequestTitle) {
                rescheduleRequestTitle.textContent = `Choose a new appointment date for ${requesterName}.`;
            }
            if (rescheduleCalendar) {
                rescheduleCalendar.setDate(currentDate);
            }
            window.bootstrap.Modal.getOrCreateInstance(rescheduleModalEl).show();
        });
    });

    bulkRescheduleButton?.addEventListener('click', () => {
        if (!rescheduleModalEl || !window.bootstrap || !window.bootstrap.Modal) return;
        const selectedIds = acceptedCheckboxes
            .filter((checkbox) => checkbox.checked)
            .map((checkbox) => checkbox.value);
        if (!selectedIds.length) {
            return;
        }
        if (rescheduleActionInput) rescheduleActionInput.value = 'bulk_reschedule';
        if (rescheduleRequestId) rescheduleRequestId.value = '';
        appendSelectedRequestIds(selectedIds);
        if (rescheduleRequestTitle) {
            rescheduleRequestTitle.textContent = `Choose a new appointment date for ${selectedIds.length} selected schedule(s).`;
        }
        if (rescheduleCalendar) {
            rescheduleCalendar.setDate('');
        }
        window.bootstrap.Modal.getOrCreateInstance(rescheduleModalEl).show();
    });
})();
