(() => {
    const openOptionsBtn = document.getElementById('open-photo-options-btn');
    const photoOptionModal = document.getElementById('photo-option-modal');
    const uploadOptionBtn = document.getElementById('photo-option-upload');
    const captureOptionBtn = document.getElementById('photo-option-capture');
    const closeOptionBtns = document.querySelectorAll('[data-photo-option-close]');
    const cameraCaptureModal = document.getElementById('camera-capture-modal');
    const cameraModalCloseBtns = document.querySelectorAll('[data-camera-capture-close]');
    const photoCountText = document.getElementById('selected-photo-count');
    const formPhotoSummary = document.getElementById('selected-photo-summary');
    const uploadInput = document.getElementById('dog_images');
    const mobileCameraInput = document.getElementById('dog_camera_images');
    const cameraGroup = document.getElementById('camera-capture-group');
    const openCameraBtn = document.getElementById('open-camera-btn');
    const takePhotoBtn = document.getElementById('take-photo-btn');
    const switchCameraBtn = document.getElementById('switch-camera-btn');
    const stopCameraBtn = document.getElementById('stop-camera-btn');
    const saveBtn = document.getElementById('camera-save-btn');
    const preview = document.getElementById('camera-preview');
    const canvas = document.getElementById('camera-canvas');
    const photoList = document.getElementById('captured-photo-list');
    const capturedInput = document.getElementById('captured_camera_images');
    const form = document.getElementById('registration-form');
    const cameraStatusText = document.getElementById('camera-status-text');

    if (
        !openOptionsBtn ||
        !photoOptionModal ||
        !uploadOptionBtn ||
        !captureOptionBtn ||
        !cameraCaptureModal ||
        !photoCountText ||
        !formPhotoSummary ||
        !uploadInput ||
        !mobileCameraInput ||
        !cameraGroup ||
        !openCameraBtn ||
        !takePhotoBtn ||
        !switchCameraBtn ||
        !stopCameraBtn ||
        !saveBtn ||
        !preview ||
        !canvas ||
        !photoList ||
        !capturedInput ||
        !cameraStatusText
    ) {
        return;
    }

    const supportsDataTransfer = typeof DataTransfer !== 'undefined';
    const supportsCamera = !!(
        navigator.mediaDevices &&
        typeof navigator.mediaDevices.getUserMedia === 'function'
    );
    const isLikelyMobileDevice = Boolean(
        (navigator.userAgentData && navigator.userAgentData.mobile) ||
        /android|iphone|ipad|ipod/i.test(navigator.userAgent || '') ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
    );

    const capturedFiles = [];
    let stream = null;
    let mirrorCompensation = false;
    let preferredFacingMode = 'environment';
    let activeFacingMode = '';
    let availableVideoInputCount = 0;

    function openPicker(input) {
        try {
            if (typeof input.showPicker === 'function') {
                input.showPicker();
                return;
            }
        } catch (error) {
            // Fallback to click when showPicker cannot be used.
        }
        input.click();
    }

    function cameraFacingLabel(mode = activeFacingMode || preferredFacingMode) {
        return mode === 'user' ? 'front' : 'rear';
    }

    function titleCaseCameraLabel(mode = activeFacingMode || preferredFacingMode) {
        const label = cameraFacingLabel(mode);
        return label.charAt(0).toUpperCase() + label.slice(1);
    }

    function nextFacingMode() {
        return preferredFacingMode === 'environment' ? 'user' : 'environment';
    }

    function getControlLabel(button) {
        return button?.querySelector('.camera-control-label') || null;
    }

    function setControlIcon(button, iconClass) {
        const icon = button?.querySelector('.camera-control-icon i');
        if (icon) {
            icon.className = `bi ${iconClass}`;
        }
    }

    function updateCameraStatus(message, tone = 'neutral') {
        cameraStatusText.textContent = message;
        cameraStatusText.dataset.tone = tone;
    }

    function updateSwitchCameraButton() {
        const label = getControlLabel(switchCameraBtn);
        if (label) {
            label.textContent = nextFacingMode() === 'user' ? 'Use Front Camera' : 'Use Rear Camera';
        }
        setControlIcon(switchCameraBtn, 'bi-arrow-repeat');
    }

    function updateCameraButtons() {
        const isStreaming = !!stream;
        const canSwitch = isLikelyMobileDevice || availableVideoInputCount > 1;
        const openLabel = getControlLabel(openCameraBtn);

        if (openLabel) {
            openLabel.textContent = isStreaming ? 'Restart Camera' : 'Open Camera';
        }
        setControlIcon(openCameraBtn, isStreaming ? 'bi-arrow-clockwise' : 'bi-camera-fill');
        openCameraBtn.classList.toggle('is-streaming', isStreaming);

        takePhotoBtn.disabled = !isStreaming;
        takePhotoBtn.classList.toggle('is-active', isStreaming);
        stopCameraBtn.disabled = !isStreaming;
        switchCameraBtn.disabled = !canSwitch;
        updateSwitchCameraButton();
    }

    async function refreshAvailableVideoInputs() {
        if (!(navigator.mediaDevices && typeof navigator.mediaDevices.enumerateDevices === 'function')) {
            availableVideoInputCount = isLikelyMobileDevice ? 2 : 0;
            updateCameraButtons();
            return;
        }

        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const videoInputs = devices.filter((device) => device.kind === 'videoinput');
            availableVideoInputCount = videoInputs.length || (isLikelyMobileDevice ? 2 : 0);
        } catch (error) {
            availableVideoInputCount = isLikelyMobileDevice ? 2 : availableVideoInputCount;
        }

        updateCameraButtons();
    }

    function replaceInputFiles(input, files) {
        if (!supportsDataTransfer) {
            return false;
        }
        const transfer = new DataTransfer();
        files.forEach((file) => transfer.items.add(file));
        input.files = transfer.files;
        return true;
    }

    function renderFormPhotoSummary() {
        formPhotoSummary.innerHTML = '';

        const selectedFiles = [];
        Array.from(uploadInput.files || []).forEach((file, index) => {
            selectedFiles.push({ file, label: 'Upload', source: 'upload', index });
        });
        Array.from(mobileCameraInput.files || []).forEach((file, index) => {
            selectedFiles.push({ file, label: 'Mobile', source: 'mobile', index });
        });
        capturedFiles.forEach((file, index) => {
            selectedFiles.push({ file, label: 'Capture', source: 'captured', index });
        });

        if (!selectedFiles.length) {
            formPhotoSummary.innerHTML = '<p class="selected-photo-empty">No photo preview yet.</p>';
            return;
        }

        selectedFiles.forEach((entry, displayIndex) => {
            const item = document.createElement('figure');
            item.className = 'selected-photo-item';

            const imageUrl = URL.createObjectURL(entry.file);
            const img = document.createElement('img');
            img.src = imageUrl;
            img.alt = `Selected photo ${displayIndex + 1}`;
            img.className = 'selected-photo-thumb';
            img.loading = 'lazy';
            img.addEventListener('load', () => URL.revokeObjectURL(imageUrl), { once: true });

            const badge = document.createElement('span');
            badge.className = 'selected-photo-badge';
            badge.textContent = entry.label;

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'selected-photo-remove';
            removeBtn.setAttribute('aria-label', 'Remove selected photo');
            removeBtn.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
            removeBtn.addEventListener('click', () => removeSummaryEntry(entry.source, entry.index));

            item.appendChild(img);
            item.appendChild(badge);
            item.appendChild(removeBtn);
            formPhotoSummary.appendChild(item);
        });
    }

    function updatePhotoCount() {
        const total =
            Array.from(uploadInput.files || []).length +
            Array.from(mobileCameraInput.files || []).length +
            capturedFiles.length;
        photoCountText.textContent = total ? `${total} photo(s) selected.` : 'No photos selected.';
        renderFormPhotoSummary();
    }

    function updateCameraSaveButton() {
        saveBtn.disabled = capturedFiles.length === 0;
    }

    function removeSummaryEntry(source, index) {
        if (source === 'captured') {
            capturedFiles.splice(index, 1);
            syncCapturedInput();
            return;
        }

        if (source === 'upload') {
            const nextFiles = Array.from(uploadInput.files || []).filter((_, fileIndex) => fileIndex !== index);
            if (replaceInputFiles(uploadInput, nextFiles)) {
                updatePhotoCount();
            }
            return;
        }

        const nextFiles = Array.from(mobileCameraInput.files || []).filter((_, fileIndex) => fileIndex !== index);
        if (replaceInputFiles(mobileCameraInput, nextFiles)) {
            updatePhotoCount();
        }
    }

    function renderCapturedThumbnails() {
        photoList.innerHTML = '';
        capturedFiles.forEach((file, index) => {
            const item = document.createElement('div');
            item.className = 'captured-photo-item';

            const imageUrl = URL.createObjectURL(file);
            const img = document.createElement('img');
            img.src = imageUrl;
            img.alt = 'Captured photo';
            img.className = 'captured-photo-thumb';
            img.addEventListener('load', () => URL.revokeObjectURL(imageUrl), { once: true });

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'captured-photo-remove';
            removeBtn.setAttribute('aria-label', 'Remove captured photo');
            removeBtn.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
            removeBtn.addEventListener('click', () => {
                capturedFiles.splice(index, 1);
                syncCapturedInput();
            });

            item.appendChild(img);
            item.appendChild(removeBtn);
            photoList.appendChild(item);
        });
    }

    function syncCapturedInput() {
        if (!supportsDataTransfer) {
            capturedInput.value = '';
            updatePhotoCount();
            updateCameraSaveButton();
            renderCapturedThumbnails();
            return;
        }

        const transfer = new DataTransfer();
        capturedFiles.forEach((file) => transfer.items.add(file));
        capturedInput.files = transfer.files;
        updatePhotoCount();
        updateCameraSaveButton();
        renderCapturedThumbnails();
    }

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach((track) => track.stop());
            stream = null;
        }
        activeFacingMode = '';
        mirrorCompensation = false;
        preview.srcObject = null;
        preview.classList.remove('camera-preview--mirror-fix');
        updateCameraStatus(`${titleCaseCameraLabel(preferredFacingMode)} camera selected. Open camera to begin.`);
        updateCameraButtons();
    }

    function openOptionModal() {
        photoOptionModal.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    function closeOptionModal() {
        photoOptionModal.hidden = true;
        document.body.style.overflow = '';
    }

    function openCameraModal() {
        cameraCaptureModal.hidden = false;
        document.body.style.overflow = 'hidden';
        updateCameraStatus(`${titleCaseCameraLabel(preferredFacingMode)} camera selected. Open camera to begin.`);
        updateCameraSaveButton();
        updateCameraButtons();
        refreshAvailableVideoInputs();
    }

    function closeCameraModal() {
        stopCamera();
        cameraCaptureModal.hidden = true;
        document.body.style.overflow = '';
    }

    function applyMirrorCompensation() {
        mirrorCompensation = activeFacingMode === 'user';
        preview.classList.toggle('camera-preview--mirror-fix', mirrorCompensation);
    }

    function cameraHelpMessage() {
        if (!window.isSecureContext) {
            return 'Camera preview requires HTTPS. You can still use your phone camera through the browser file picker.';
        }
        if (!supportsCamera) {
            return 'Live camera preview is not available in this browser. You can still use your phone camera through the browser file picker.';
        }
        return 'Unable to open the camera. Check browser camera permission and try again.';
    }

    async function requestCameraStream(facingMode) {
        const attempts = [];
        const resolutionPreferences = {
            width: { ideal: 1280 },
            height: { ideal: 960 }
        };

        if (facingMode) {
            attempts.push({ video: { facingMode: { exact: facingMode }, ...resolutionPreferences }, audio: false });
            attempts.push({ video: { facingMode: { ideal: facingMode }, ...resolutionPreferences }, audio: false });
        }
        attempts.push({ video: resolutionPreferences, audio: false });
        attempts.push({ video: true, audio: false });

        let lastError = null;
        for (const constraints of attempts) {
            try {
                return await navigator.mediaDevices.getUserMedia(constraints);
            } catch (error) {
                lastError = error;
            }
        }
        throw lastError;
    }

    function openNativeCameraFallback() {
        stopCamera();
        mobileCameraInput.setAttribute('capture', preferredFacingMode);
        mobileCameraInput.removeAttribute('multiple');
        closeCameraModal();
        openPicker(mobileCameraInput);
    }

    async function startCameraPreview() {
        if (!supportsDataTransfer) {
            openNativeCameraFallback();
            return;
        }

        if (!supportsCamera || !window.isSecureContext) {
            if (isLikelyMobileDevice) {
                openNativeCameraFallback();
                return;
            }
            updateCameraStatus('Unable to open camera.', 'error');
            alert(cameraHelpMessage());
            return;
        }

        stopCamera();
        updateCameraStatus(`Opening ${cameraFacingLabel(preferredFacingMode)} camera...`, 'info');

        try {
            stream = await requestCameraStream(preferredFacingMode);
            preview.srcObject = stream;

            const track = stream.getVideoTracks()[0];
            const settings = track && typeof track.getSettings === 'function' ? track.getSettings() : {};
            activeFacingMode = settings.facingMode || preferredFacingMode;
            preferredFacingMode = activeFacingMode;
            applyMirrorCompensation();
            await refreshAvailableVideoInputs();

            if (preview.readyState < 1) {
                await new Promise((resolve) => {
                    preview.onloadedmetadata = () => resolve();
                });
            }
            if (typeof preview.play === 'function') {
                await preview.play().catch(() => {});
            }

            updateCameraStatus(`${titleCaseCameraLabel(activeFacingMode)} camera is live.`, 'success');
            updateCameraButtons();
        } catch (error) {
            if (isLikelyMobileDevice) {
                openNativeCameraFallback();
                return;
            }
            stopCamera();
            updateCameraStatus('Unable to open camera.', 'error');
            alert(cameraHelpMessage());
        }
    }

    function toggleCameraFacingMode() {
        preferredFacingMode = nextFacingMode();
        updateSwitchCameraButton();

        if (stream) {
            startCameraPreview();
            return;
        }

        updateCameraStatus(`${titleCaseCameraLabel(preferredFacingMode)} camera selected. Open camera to begin.`);
        updateCameraButtons();
    }

    openOptionsBtn.addEventListener('click', openOptionModal);
    closeOptionBtns.forEach((button) => button.addEventListener('click', closeOptionModal));

    uploadOptionBtn.addEventListener('click', () => {
        closeOptionModal();
        uploadInput.removeAttribute('capture');
        uploadInput.setAttribute('multiple', '');
        openPicker(uploadInput);
    });

    captureOptionBtn.addEventListener('click', () => {
        closeOptionModal();
        if (supportsDataTransfer) {
            openCameraModal();
            openCameraBtn.focus();
            return;
        }

        mobileCameraInput.setAttribute('capture', preferredFacingMode);
        openPicker(mobileCameraInput);
    });

    cameraModalCloseBtns.forEach((button) => button.addEventListener('click', closeCameraModal));
    openCameraBtn.addEventListener('click', startCameraPreview);
    switchCameraBtn.addEventListener('click', toggleCameraFacingMode);
    stopCameraBtn.addEventListener('click', stopCamera);

    takePhotoBtn.addEventListener('click', () => {
        if (!preview.videoWidth) {
            alert('Open the camera first before capturing.');
            return;
        }

        canvas.width = preview.videoWidth;
        canvas.height = preview.videoHeight;
        const context = canvas.getContext('2d');
        if (!context) {
            return;
        }

        if (mirrorCompensation) {
            context.save();
            context.translate(canvas.width, 0);
            context.scale(-1, 1);
            context.drawImage(preview, 0, 0, canvas.width, canvas.height);
            context.restore();
        } else {
            context.drawImage(preview, 0, 0, canvas.width, canvas.height);
        }

        canvas.toBlob((blob) => {
            if (!blob) {
                return;
            }
            capturedFiles.push(new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' }));
            syncCapturedInput();
            updateCameraStatus('Photo captured. You can take another photo or tap Done.', 'success');
        }, 'image/jpeg', 0.92);
    });

    saveBtn.addEventListener('click', closeCameraModal);
    uploadInput.addEventListener('change', updatePhotoCount);
    mobileCameraInput.addEventListener('change', updatePhotoCount);

    if (form) {
        form.addEventListener('submit', stopCamera);
    }
    window.addEventListener('beforeunload', stopCamera);

    updatePhotoCount();
    updateCameraSaveButton();
    updateCameraButtons();
    refreshAvailableVideoInputs();
})();
