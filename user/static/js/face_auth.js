(function () {
    const app = document.getElementById("faceAuthApp");
    if (!app) {
        return;
    }

    const video = document.getElementById("video");
    const canvas = document.getElementById("canvas");
    const analysisCanvas = document.getElementById("analysisCanvas");
    const stepLabel = document.getElementById("stepLabel");
    const stepCounter = document.getElementById("stepCounter");
    const instructionTitle = document.getElementById("instructionTitle");
    const instructionDesc = document.getElementById("instructionDesc");
    const statusText = document.getElementById("status");
    const liveHint = document.getElementById("liveHint");
    const liveHintText = document.getElementById("liveHintText");
    const cameraStage = document.querySelector(".camera-stage");
    const cameraCircle = document.querySelector(".camera-circle");
    const retryCameraBtn = document.getElementById("retryCameraBtn");
    const restartCaptureBtn = document.getElementById("restartCaptureBtn");
    const termsSection = document.getElementById("termsSection");
    const agreeTermsCheckbox = document.getElementById("agreeTermsCheckbox");
    const completeSignupBtn = document.getElementById("completeSignupBtn");
    const stepIndicators = Array.from(document.querySelectorAll("[data-step-indicator]"));
    const csrfInput = document.querySelector('#csrf-form input[name="csrfmiddlewaretoken"]');
    const completeSignupForm = document.getElementById("completeSignupForm");

    const csrftoken = csrfInput ? csrfInput.value : "";
    const saveFaceUrl = app.dataset.saveFaceUrl;
    const resetSignupCaptureUrl = app.dataset.resetSignupCaptureUrl;
    const expectedCaptureCount = Number(app.dataset.expectedCaptures || "4");
    const termsRequiredOnLoad = app.dataset.termsRequired === "true";

    const STEPS = [
        { key: "LOOK_FORWARD", title: "Look Straight", desc: "Center your face in the guide." },
        { key: "TURN_LEFT", title: "Turn Left", desc: "Turn your head slightly to the left." },
        { key: "TURN_RIGHT", title: "Turn Right", desc: "Turn your head slightly to the right." },
        { key: "BLINK", title: "Blink", desc: "Blink once when you are ready." }
    ];
    const REQUIRED_STABLE_FRAMES = 6;
    const STABLE_HOLD_MS = 240;
    const MOTION_THRESHOLD = 0.012;
    const MAX_AUTO_CAMERA_RETRIES = 1;
    const STEP_ASSIST_TIMEOUT_MS = 7000;

    let images = [];
    let step = 0;
    let lastCaptureTime = 0;
    let lastHintUpdateTime = 0;
    let stableFrames = 0;
    let holdStartTime = 0;
    let previousSample = null;
    let lowLightStreak = 0;
    let mediaStream = null;
    let processingActive = false;
    let faceMeshBusy = false;
    let autoRetryCount = 0;
    let uploadDone = false;
    let uploadInProgress = false;
    let finalizingSignup = false;
    let cameraLost = false;
    let stepStartedAt = Date.now();

    const faceMesh = new FaceMesh({
        locateFile: function (file) {
            return "https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/" + file;
        }
    });

    faceMesh.setOptions({
        maxNumFaces: 1,
        refineLandmarks: false,
        minDetectionConfidence: 0.35,
        minTrackingConfidence: 0.35
    });

    faceMesh.onResults(onResults);

    function setStatus(message) {
        if (statusText) {
            statusText.innerText = message;
        }
    }

    function setLiveHint(message, type) {
        if (liveHintText) {
            liveHintText.innerText = message;
        }
        if (liveHint) {
            liveHint.classList.remove("live-hint--info", "live-hint--warning", "live-hint--success", "live-hint--error");
            liveHint.classList.add("live-hint--" + (type || "info"));
        }
    }

    function setCaptureState(state) {
        if (!cameraCircle) {
            return;
        }
        cameraCircle.classList.remove("capture-prep", "capture-done", "capture-error");
        if (state === "capturing") {
            cameraCircle.classList.add("capture-prep");
        } else if (state === "done") {
            cameraCircle.classList.add("capture-done");
            window.setTimeout(function () {
                cameraCircle.classList.remove("capture-done");
            }, 750);
        } else if (state === "error") {
            cameraCircle.classList.add("capture-error");
        }
    }

    function showRetryCamera(visible) {
        if (retryCameraBtn) {
            retryCameraBtn.hidden = !visible;
        }
    }

    function showRestartCapture(visible) {
        if (restartCaptureBtn) {
            restartCaptureBtn.hidden = !visible;
        }
    }

    function hasPendingCapturedState() {
        return Boolean(images.length || uploadDone || uploadInProgress || termsRequiredOnLoad || (termsSection && !termsSection.hidden));
    }

    function resetSignupCaptureOnServer() {
        if (!resetSignupCaptureUrl || finalizingSignup || !hasPendingCapturedState()) {
            return;
        }

        try {
            fetch(resetSignupCaptureUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrftoken
                },
                body: "{}",
                credentials: "same-origin",
                keepalive: true
            });
        } catch (error) {
            // Best-effort cleanup only.
        }
    }

    function showCameraStage() {
        if (cameraStage) {
            cameraStage.hidden = false;
        }
        if (termsSection) {
            termsSection.hidden = true;
        }
    }

    function showTermsStage() {
        if (cameraStage) {
            cameraStage.hidden = true;
        }
        if (termsSection) {
            termsSection.hidden = false;
        }
    }

    function updateStepUI() {
        const isComplete = step >= STEPS.length;
        stepLabel.innerText = isComplete ? "Complete" : "Step " + (step + 1);
        stepCounter.innerText = isComplete
            ? STEPS.length + " / " + STEPS.length
            : (step + 1) + " / " + STEPS.length;

        stepIndicators.forEach(function (indicator, index) {
            indicator.classList.toggle("is-complete", index < step);
            indicator.classList.toggle("is-active", !isComplete && index === step);
        });

        if (isComplete) {
            instructionTitle.innerText = "Capture Successful";
            instructionDesc.innerText = "Uploading your Face ID images securely.";
            return;
        }

        instructionTitle.innerText = STEPS[step].title;
        instructionDesc.innerText = STEPS[step].desc;
    }

    function buildCameraConstraints() {
        const supported = navigator.mediaDevices && typeof navigator.mediaDevices.getSupportedConstraints === "function"
            ? navigator.mediaDevices.getSupportedConstraints()
            : {};
        const preferredVideo = {};

        if (supported.facingMode) {
            preferredVideo.facingMode = { ideal: "user" };
        }
        if (supported.width) {
            preferredVideo.width = { ideal: 640 };
        }
        if (supported.height) {
            preferredVideo.height = { ideal: 480 };
        }

        return [
            { audio: false, video: Object.keys(preferredVideo).length ? preferredVideo : true },
            { audio: false, video: true },
        ];
    }

    function hasCameraApi() {
        return !!(navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function");
    }

    async function getCameraPermissionState() {
        if (!navigator.permissions || typeof navigator.permissions.query !== "function") {
            return "unknown";
        }
        try {
            const result = await navigator.permissions.query({ name: "camera" });
            return result.state || "unknown";
        } catch (error) {
            return "unknown";
        }
    }

    function waitForVideoReady() {
        return new Promise(function (resolve, reject) {
            if (video.readyState >= 2 && video.videoWidth > 0) {
                resolve();
                return;
            }

            const timeoutId = window.setTimeout(function () {
                cleanup();
                reject(new Error("Video stream timed out."));
            }, 5000);

            function cleanup() {
                window.clearTimeout(timeoutId);
                video.removeEventListener("loadedmetadata", onReady);
                video.removeEventListener("canplay", onReady);
                video.removeEventListener("error", onError);
            }

            function onReady() {
                cleanup();
                resolve();
            }

            function onError() {
                cleanup();
                reject(new Error("Video stream could not start."));
            }

            video.addEventListener("loadedmetadata", onReady, { once: true });
            video.addEventListener("canplay", onReady, { once: true });
            video.addEventListener("error", onError, { once: true });
        });
    }

    function stopCamera() {
        processingActive = false;
        faceMeshBusy = false;
        if (mediaStream) {
            mediaStream.getTracks().forEach(function (track) {
                track.stop();
            });
        }
        mediaStream = null;
        if (video) {
            video.srcObject = null;
        }
    }

    async function startCameraWithConstraints(constraints) {
        stopCamera();
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        mediaStream = stream;
        cameraLost = false;
        stream.getVideoTracks().forEach(function (track) {
            track.addEventListener("ended", function () {
                if (!finalizingSignup && !uploadInProgress) {
                    cameraLost = true;
                    handleCameraFailure(new Error("Camera stream ended unexpectedly."), false);
                }
            });
        });
        video.srcObject = stream;
        video.muted = true;
        await waitForVideoReady();
        try {
            await video.play();
        } catch (error) {
            // iOS sometimes resolves the stream before play() is allowed; keep going if metadata exists.
        }
        setCaptureState("idle");
    }

    async function startCameraWithFallbacks() {
        const cameraConstraints = buildCameraConstraints();
        let lastError = null;
        for (let index = 0; index < cameraConstraints.length; index += 1) {
            try {
                await startCameraWithConstraints(cameraConstraints[index]);
                return;
            } catch (error) {
                lastError = error;
            }
        }
        throw lastError || new Error("Unable to start camera.");
    }

    function startProcessingLoop() {
        processingActive = true;

        async function tick() {
            if (!processingActive || !mediaStream || uploadDone || uploadInProgress || finalizingSignup) {
                return;
            }
            if (video.readyState >= 2 && !faceMeshBusy) {
                faceMeshBusy = true;
                try {
                    await faceMesh.send({ image: video });
                } catch (error) {
                    setLiveHint("Face tracking paused. Trying to recover...", "warning");
                } finally {
                    faceMeshBusy = false;
                }
            }
            window.requestAnimationFrame(tick);
        }

        window.requestAnimationFrame(tick);
    }

    async function initializeCameraFlow(isManualRetry) {
        if (uploadDone || uploadInProgress || finalizingSignup) {
            return;
        }

        if (!window.isSecureContext) {
            setCaptureState("error");
            setStatus("Camera requires HTTPS on mobile browsers.");
            setLiveHint("Open this page on HTTPS or localhost to use Face ID.", "error");
            showRetryCamera(true);
            return;
        }

        if (!hasCameraApi()) {
            setCaptureState("error");
            setStatus("This browser does not support camera capture.");
            setLiveHint("Try Chrome, Edge, Safari, or Firefox on a secure connection.", "error");
            showRetryCamera(false);
            return;
        }

        showRetryCamera(false);
        setStatus("Camera starting...");
        setLiveHint("Camera starting. Allow access if your browser asks.", "info");

        const permissionState = await getCameraPermissionState();
        if (permissionState === "denied") {
            setCaptureState("error");
            setStatus("Camera access is blocked.");
            setLiveHint("Enable camera permission in your browser settings, then retry.", "error");
            showRetryCamera(true);
            return;
        }

        if (permissionState === "prompt") {
            setLiveHint("Please allow camera access to continue.", "warning");
        }

        try {
            await startCameraWithFallbacks();
            autoRetryCount = 0;
            setStatus("Align your face with the guide.");
            setLiveHint("Align your face and hold still for automatic capture.", "success");
            showRestartCapture(true);
            startProcessingLoop();
        } catch (error) {
            handleCameraFailure(error, !isManualRetry);
        }
    }

    function handleCameraFailure(error, allowAutoRetry) {
        stopCamera();
        setCaptureState("error");
        showRetryCamera(true);
        showRestartCapture(images.length > 0);

        const errorName = error && error.name ? error.name : "";
        let message = "Unable to open the camera. Check browser permission and try again.";

        if (errorName === "NotAllowedError" || errorName === "PermissionDeniedError") {
            message = "Camera access was denied. Allow access and retry.";
        } else if (errorName === "NotFoundError" || errorName === "DevicesNotFoundError") {
            message = "No front camera was found on this device.";
        } else if (errorName === "NotReadableError" || errorName === "TrackStartError") {
            message = "Camera is busy in another app. Close it and retry.";
        } else if (cameraLost) {
            message = "Camera connection was interrupted. Retrying can continue the capture.";
        }

        setStatus(message);
        setLiveHint(message, "error");

        if (allowAutoRetry && autoRetryCount < MAX_AUTO_CAMERA_RETRIES) {
            autoRetryCount += 1;
            setStatus("Camera failed to start. Retrying...");
            setLiveHint("Retrying camera automatically...", "warning");
            window.setTimeout(function () {
                initializeCameraFlow(false);
            }, 1200);
        }
    }

    function headYaw(landmarks) {
        const nose = landmarks[1].x;
        const leftCheek = landmarks[234].x;
        const rightCheek = landmarks[454].x;
        const faceWidth = rightCheek - leftCheek;
        const faceCenter = leftCheek + faceWidth / 2;
        return (nose - faceCenter) / faceWidth;
    }

    function isBlinking(landmarks) {
        const leftEye = landmarks[145].y - landmarks[159].y;
        const rightEye = landmarks[374].y - landmarks[386].y;
        return ((leftEye + rightEye) / 2) < 0.014;
    }

    function checkStep(landmarks) {
        const yaw = headYaw(landmarks);
        switch (STEPS[step].key) {
            case "LOOK_FORWARD":
                return Math.abs(yaw) < 0.09;
            case "TURN_LEFT":
                return yaw > 0.1;
            case "TURN_RIGHT":
                return yaw < -0.1;
            case "BLINK":
                return isBlinking(landmarks);
            default:
                return false;
        }
    }

    function landmarkSample(landmarks) {
        const ids = [1, 33, 263, 61, 291, 152];
        return ids.map(function (idx) {
            return { x: landmarks[idx].x, y: landmarks[idx].y };
        });
    }

    function isFaceStable(landmarks) {
        const current = landmarkSample(landmarks);
        if (!previousSample) {
            previousSample = current;
            return false;
        }

        let total = 0;
        for (let index = 0; index < current.length; index += 1) {
            total += Math.abs(current[index].x - previousSample[index].x)
                + Math.abs(current[index].y - previousSample[index].y);
        }
        const motion = total / current.length;
        previousSample = current;
        return motion < MOTION_THRESHOLD;
    }

    function resetHoldTimerOnly() {
        holdStartTime = 0;
    }

    function resetStability() {
        stableFrames = 0;
        holdStartTime = 0;
        previousSample = null;
    }

    function getBrightnessScore() {
        if (!video.videoWidth || !video.videoHeight) {
            return 120;
        }

        analysisCanvas.width = 64;
        analysisCanvas.height = 48;
        const context = analysisCanvas.getContext("2d", { willReadFrequently: true });
        context.drawImage(video, 0, 0, 64, 48);
        const data = context.getImageData(0, 0, 64, 48).data;
        let total = 0;
        for (let index = 0; index < data.length; index += 4) {
            total += (data[index] * 0.299) + (data[index + 1] * 0.587) + (data[index + 2] * 0.114);
        }
        return total / (64 * 48);
    }

    function evaluateReadiness(landmarks) {
        const nose = landmarks[1];
        const yaw = headYaw(landmarks);
        const brightness = getBrightnessScore();

        if (brightness < 55) {
            lowLightStreak += 1;
            if (lowLightStreak < 30) {
                return { ready: false, hint: "Too dark. Move toward brighter light.", type: "warning" };
            }
            return { ready: true, hint: "Low light detected. Hold still.", type: "warning" };
        }

        lowLightStreak = 0;
        if (nose.y < 0.28) {
            return { ready: false, hint: "Move down a little.", type: "warning" };
        }
        if (nose.y > 0.74) {
            return { ready: false, hint: "Move up a little.", type: "warning" };
        }
        if (nose.x < 0.26) {
            return { ready: false, hint: "Move slightly right.", type: "warning" };
        }
        if (nose.x > 0.74) {
            return { ready: false, hint: "Move slightly left.", type: "warning" };
        }

        if (STEPS[step].key === "LOOK_FORWARD" && Math.abs(yaw) > 0.11) {
            return { ready: false, hint: "Look straight at the camera.", type: "warning" };
        }
        if (STEPS[step].key === "TURN_LEFT" && yaw <= 0.08) {
            return { ready: false, hint: "Turn more left.", type: "warning" };
        }
        if (STEPS[step].key === "TURN_RIGHT" && yaw >= -0.08) {
            return { ready: false, hint: "Turn more right.", type: "warning" };
        }
        if (STEPS[step].key === "BLINK") {
            return { ready: true, hint: "Blink once now.", type: "info" };
        }
        return { ready: true, hint: "Ready. Hold still.", type: "success" };
    }

    function shouldUseAssistedCapture(readiness) {
        if (!readiness.ready) {
            return false;
        }
        return (Date.now() - stepStartedAt) >= STEP_ASSIST_TIMEOUT_MS;
    }

    function advanceStep() {
        setCaptureState("done");
        resetStability();
        step += 1;
        stepStartedAt = Date.now();
        updateStepUI();
        setStatus("Capture " + step + "/" + STEPS.length + " successful.");
        if (step >= STEPS.length) {
            uploadImages();
        }
    }

    function canCapture() {
        const now = Date.now();
        if (now - lastCaptureTime > 1200) {
            lastCaptureTime = now;
            return true;
        }
        return false;
    }

    function captureImage() {
        canvas.width = 480;
        canvas.height = 360;
        const context = canvas.getContext("2d");
        context.save();
        context.scale(-1, 1);
        context.drawImage(video, -canvas.width, 0, canvas.width, canvas.height);
        context.restore();
        images.push(canvas.toDataURL("image/jpeg", 0.75));
    }

    function resetCaptureSequence(clearImages) {
        showCameraStage();
        step = 0;
        stepStartedAt = Date.now();
        lastCaptureTime = 0;
        lastHintUpdateTime = 0;
        lowLightStreak = 0;
        resetStability();
        uploadDone = false;
        uploadInProgress = false;
        finalizingSignup = false;
        if (clearImages) {
            images = [];
        }
        updateStepUI();
        setCaptureState("idle");
        setStatus("Camera starting...");
        setLiveHint("Camera starting...", "info");
    }

    function showTermsAndConditions() {
        stopCamera();
        showTermsStage();
        showRetryCamera(false);
        showRestartCapture(false);
        setCaptureState("idle");
        step = STEPS.length;
        updateStepUI();
        setStatus("Face ID capture complete. Review the terms to finish signup.");
        setLiveHint("Capture successful. Review and accept the terms to complete signup.", "success");
        instructionTitle.innerText = "Terms and Conditions";
        instructionDesc.innerText = "Your four captures are complete. Agree below to finish signup.";
        if (agreeTermsCheckbox) {
            agreeTermsCheckbox.checked = false;
        }
        if (completeSignupBtn) {
            completeSignupBtn.disabled = true;
        }
    }

    async function uploadImages() {
        if (uploadInProgress || finalizingSignup) {
            return;
        }

        stopCamera();
        uploadDone = true;
        uploadInProgress = true;
        setStatus("Capture successful. Camera stopped. Uploading securely...");
        setLiveHint("Uploading your Face ID images securely.", "success");
        showRetryCamera(false);
        showRestartCapture(false);

        try {
            const response = await fetch(saveFaceUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrftoken
                },
                body: JSON.stringify({ images: images.slice(0, expectedCaptureCount) })
            });
            const data = await response.json();
            if (!response.ok || data.status !== "ok") {
                throw new Error(data.message || "Unable to save face captures.");
            }
            uploadInProgress = false;
            showTermsAndConditions();
        } catch (error) {
            uploadDone = false;
            uploadInProgress = false;
            setCaptureState("error");
            setStatus("Upload failed. Please retry the capture.");
            setLiveHint(error.message || "Upload failed. Please retry the capture.", "error");
            showCameraStage();
            showRestartCapture(true);
            showRetryCamera(true);
        }
    }

    function onResults(results) {
        if (uploadDone || uploadInProgress || finalizingSignup || step >= STEPS.length) {
            return;
        }

        if (!results.multiFaceLandmarks || !results.multiFaceLandmarks.length) {
            resetStability();
            setCaptureState("idle");
            if (Date.now() - lastHintUpdateTime > 250) {
                setLiveHint("No face detected yet. Move closer and face the camera directly.", "warning");
                setStatus("Align your face with the guide.");
                lastHintUpdateTime = Date.now();
            }
            return;
        }

        const landmarks = results.multiFaceLandmarks[0];
        const readiness = evaluateReadiness(landmarks);
        const stepPassed = checkStep(landmarks);
        const assistedCapture = shouldUseAssistedCapture(readiness);

        if (Date.now() - lastHintUpdateTime > 250) {
            if (assistedCapture) {
                setLiveHint("Detection assist is active. Hold still for capture.", "success");
            } else {
                setLiveHint(readiness.hint, readiness.type || "info");
            }
            lastHintUpdateTime = Date.now();
        }

        if (!readiness.ready || (!stepPassed && !assistedCapture)) {
            resetStability();
            setCaptureState("idle");
            if (STEPS[step].key === "BLINK") {
                setStatus("Blink once when the guide says ready.");
            } else {
                setStatus(assistedCapture ? "Hold still for assisted capture." : "Align your face and hold still.");
            }
            return;
        }

        if ((STEPS[step].key === "BLINK" || assistedCapture) && canCapture()) {
            captureImage();
            advanceStep();
            return;
        }

        if (!isFaceStable(landmarks)) {
            resetHoldTimerOnly();
            setCaptureState("idle");
            if (Date.now() - lastHintUpdateTime > 250) {
                setLiveHint("Hold still.", "warning");
                lastHintUpdateTime = Date.now();
            }
            setStatus("Align your face and hold still.");
            return;
        }

        setCaptureState("capturing");
        stableFrames += 1;
        if (stableFrames < REQUIRED_STABLE_FRAMES) {
            setStatus("Align your face and hold still.");
            return;
        }

        if (!holdStartTime) {
            holdStartTime = Date.now();
        }

        const holdRemaining = STABLE_HOLD_MS - (Date.now() - holdStartTime);
        if (holdRemaining > 0) {
            setStatus("Hold still for automatic capture...");
            if (Date.now() - lastHintUpdateTime > 250) {
                setLiveHint("Hold still... " + Math.max(0.1, holdRemaining / 1000).toFixed(1) + "s", "info");
                lastHintUpdateTime = Date.now();
            }
            return;
        }

        if (canCapture()) {
            captureImage();
            advanceStep();
        }
    }

    if (retryCameraBtn) {
        retryCameraBtn.addEventListener("click", function () {
            initializeCameraFlow(true);
        });
    }

    if (restartCaptureBtn) {
        restartCaptureBtn.addEventListener("click", function () {
            resetCaptureSequence(true);
            initializeCameraFlow(true);
        });
    }

    if (agreeTermsCheckbox && completeSignupBtn) {
        agreeTermsCheckbox.addEventListener("change", function () {
            completeSignupBtn.disabled = !agreeTermsCheckbox.checked;
        });
    }

    if (completeSignupForm) {
        completeSignupForm.addEventListener("submit", function () {
            finalizingSignup = true;
            setStatus("Terms accepted. Finalizing signup...");
            setLiveHint("Finalizing your account setup.", "success");
        });
    }

    window.addEventListener("beforeunload", function () {
        stopCamera();
        resetSignupCaptureOnServer();
    });

    window.addEventListener("pagehide", function () {
        stopCamera();
        resetSignupCaptureOnServer();
    });

    if (termsRequiredOnLoad) {
        step = STEPS.length;
        updateStepUI();
        showTermsAndConditions();
    } else {
        updateStepUI();
        resetCaptureSequence(true);
        initializeCameraFlow(false);
    }
})();
