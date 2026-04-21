(function () {
    const authForms = Array.from(document.querySelectorAll("[data-google-auth-form], [data-google-signup-form]"));
    if (!authForms.length) {
        return;
    }

    const MAX_RETRIES = 12;
    const RETRY_DELAY_MS = 150;

    function getMode(form) {
        const explicitMode = (form.dataset.googleAuthMode || "").trim().toLowerCase();
        if (explicitMode) {
            return explicitMode;
        }
        return form.hasAttribute("data-google-signup-form") ? "signup" : "login";
    }

    function isPendingSignup(form) {
        return (form.dataset.googleAuthPending || "").trim() === "1";
    }

    function getClientId(form) {
        return (form.dataset.googleClientId || "").trim();
    }

    function getCredentialInput(form) {
        return form.querySelector('input[name="google_credential"]');
    }

    function getAuthScope(form) {
        return form.closest(".auth-panel") || form.parentElement || document;
    }

    function queryAuthScope(form, selector) {
        const scope = getAuthScope(form);
        if (!scope) {
            return null;
        }
        return scope.querySelector(selector);
    }

    function getButtonTarget(form) {
        return queryAuthScope(form, "[data-google-auth-button], [data-google-signup-button]");
    }

    function getErrorOutput(form) {
        return queryAuthScope(form, "[data-google-auth-error], [data-google-signup-error]");
    }

    function getButtonShell(form) {
        return queryAuthScope(form, ".google-signup-shell");
    }

    function getRenderContext(form) {
        const modal = form.closest(".modal");
        if (!modal) {
            return "page";
        }
        if (!modal.classList.contains("show")) {
            return "";
        }
        return modal.id || "modal";
    }

    function setError(form, message) {
        const errorOutput = getErrorOutput(form);
        if (!errorOutput) {
            return;
        }
        errorOutput.textContent = message || "";
        errorOutput.classList.toggle("d-none", !message);
    }

    function clearError(form) {
        setError(form, "");
    }

    function getRenderedContext(form) {
        return (form.dataset.googleAuthRenderedContext || "").trim();
    }

    function setRenderedContext(form, context) {
        form.dataset.googleAuthRenderedContext = context;
    }

    function getRetryCount(form) {
        return parseInt(form.dataset.googleAuthRetryCount || "0", 10) || 0;
    }

    function setRetryCount(form, retryCount) {
        form.dataset.googleAuthRetryCount = String(retryCount);
    }

    function canRenderNow(form) {
        const modal = form.closest(".modal");
        return !modal || modal.classList.contains("show");
    }

    function scheduleRetry(form, message) {
        const retryCount = getRetryCount(form);
        if (retryCount >= MAX_RETRIES) {
            if (message) {
                setError(form, message);
            }
            setRenderedContext(form, getRenderContext(form));
            return;
        }

        setRetryCount(form, retryCount + 1);
        window.setTimeout(function () {
            renderAuthButton(form);
        }, RETRY_DELAY_MS);
    }

    function renderAuthButton(form, force) {
        const renderContext = getRenderContext(form);
        if (!renderContext) {
            return;
        }

        if (!canRenderNow(form)) {
            return;
        }

        if (!force && getRenderedContext(form) === renderContext) {
            return;
        }

        const mode = getMode(form);
        const pendingSignup = mode === "signup" && isPendingSignup(form);
        const clientId = getClientId(form);
        const buttonTarget = getButtonTarget(form);

        if (!buttonTarget) {
            setRenderedContext(form, renderContext);
            return;
        }

        buttonTarget.style.width = "100%";
        buttonTarget.style.display = "flex";
        buttonTarget.style.justifyContent = "center";
        buttonTarget.style.minHeight = "44px";

        if (pendingSignup) {
            const buttonShell = getButtonShell(form);
            if (buttonShell) {
                buttonShell.classList.add("d-none");
            }
            clearError(form);
            setRenderedContext(form, renderContext);
            return;
        }

        if (!clientId) {
            setError(
                form,
                mode === "login"
                    ? "Google sign-in is not configured yet. Please contact the administrator."
                    : "Google signup is not configured yet. Please contact the administrator."
            );
            setRenderedContext(form, renderContext);
            return;
        }

        if (!window.google || !window.google.accounts || !window.google.accounts.id) {
            scheduleRetry(
                form,
                mode === "login"
                    ? "Google sign-in is temporarily unavailable. Refresh and try again."
                    : "Google signup is temporarily unavailable. Refresh and try again."
            );
            return;
        }

        const buttonShell = getButtonShell(form);
        if (buttonShell) {
            buttonShell.classList.remove("d-none");
        }

        clearError(form);
        buttonTarget.innerHTML = "";

        const buttonWidth = Math.max(
            200,
            Math.min(400, Math.round(buttonTarget.getBoundingClientRect().width) || 320)
        );

        const renderOptions = {
            type: "standard",
            theme: "outline",
            size: "large",
            text: mode === "login" ? "continue_with" : "signup_with",
            shape: "rectangular",
            logo_alignment: "left",
            width: buttonWidth,
        };

        if (mode === "login") {
            window.google.accounts.id.initialize({
                client_id: clientId,
                callback: function (response) {
                    clearError(form);

                    if (!response || !response.credential) {
                        setError(form, "Google could not confirm your account. Please try again.");
                        return;
                    }

                    const credentialInput = getCredentialInput(form);
                    if (!credentialInput) {
                        setError(form, "Google could not confirm your account. Please try again.");
                        return;
                    }

                    credentialInput.value = response.credential;
                    form.submit();
                },
                auto_select: false,
                cancel_on_tap_outside: true,
                ux_mode: "popup",
            });
            window.google.accounts.id.renderButton(buttonTarget, renderOptions);
            setRenderedContext(form, renderContext);
            return;
        }

        window.google.accounts.id.initialize({
            client_id: clientId,
            callback: function (response) {
                clearError(form);

                if (!response || !response.credential) {
                    setError(form, "Google could not confirm your account. Please try again.");
                    return;
                }

                const credentialInput = getCredentialInput(form);
                if (!credentialInput) {
                    setError(form, "Google could not confirm your account. Please try again.");
                    return;
                }

                credentialInput.value = response.credential;
                form.submit();
            },
            auto_select: false,
            cancel_on_tap_outside: true,
            ux_mode: "popup",
        });

        window.google.accounts.id.renderButton(buttonTarget, renderOptions);
        setRenderedContext(form, renderContext);
    }

    function renderAuthForms(root, options) {
        const force = !!(options && options.force);
        authForms.forEach(function (form) {
            if (!root.contains(form)) {
                return;
            }
            if (root === document) {
                const modal = form.closest(".modal");
                if (modal && !modal.classList.contains("show")) {
                    return;
                }
            }
            renderAuthButton(form, force);
        });
    }

    renderAuthForms(document);

    if (window.bootstrap) {
        document.querySelectorAll(".modal").forEach(function (modalEl) {
            modalEl.addEventListener("shown.bs.modal", function () {
                renderAuthForms(modalEl, { force: true });
            });
            modalEl.addEventListener("hidden.bs.modal", function () {
                renderAuthForms(document, { force: true });
            });
        });
    }

    window.addEventListener("load", function () {
        renderAuthForms(document);
    });
})();
