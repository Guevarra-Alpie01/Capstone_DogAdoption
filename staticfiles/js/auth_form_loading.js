(function () {
    function getSubmitButton(form, submitter) {
        if (submitter && submitter.matches && submitter.matches('button[type="submit"]')) {
            return submitter;
        }
        return form.querySelector('button[type="submit"]');
    }

    function isAuthForm(form) {
        return (
            form &&
            form.tagName === "FORM" &&
            (form.classList.contains("signup-form") ||
                form.classList.contains("login-form") ||
                form.classList.contains("login-paws-form"))
        );
    }

    function getSubmitLabel(form) {
        if (form.classList.contains("signup-form")) {
            return "Creating...";
        }
        return "Signing in...";
    }

    /** Restore submit button when loading was applied (idempotent). */
    function hideSpinner(button) {
        if (!button || button.dataset.authLoadingActive !== "1") {
            return;
        }
        delete button.dataset.authLoadingActive;
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.classList.remove("auth-submit-loading");
        if (button.dataset.authLoadingOriginal != null) {
            button.innerHTML = button.dataset.authLoadingOriginal;
            delete button.dataset.authLoadingOriginal;
        }
    }

    /** Spinner + disabled submit; only for confirmed-valid synchronous POST or wrapped async flows. */
    function showSpinner(button, label) {
        if (!button || button.dataset.authLoadingActive === "1") {
            return;
        }
        var original = button.innerHTML;
        try {
            button.dataset.authLoadingOriginal = original;
            button.dataset.authLoadingActive = "1";
            button.disabled = true;
            button.setAttribute("aria-busy", "true");
            button.classList.add("auth-submit-loading");
            button.innerHTML =
                '<span class="auth-btn-loading-spinner" aria-hidden="true"></span>' +
                '<span class="auth-btn-loading-label">' +
                label +
                "</span>";
        } catch (err) {
            delete button.dataset.authLoadingOriginal;
            delete button.dataset.authLoadingActive;
            button.disabled = false;
            button.removeAttribute("aria-busy");
            button.classList.remove("auth-submit-loading");
            button.innerHTML = original;
            throw err;
        }
    }

    function tryShowSpinner(button, label) {
        try {
            showSpinner(button, label);
        } catch (err) {
            hideSpinner(button);
            throw err;
        }
    }

    /**
     * Runs an async action with spinner only while work is in flight.
     * try { showSpinner } catch { hideSpinner } finally { hideSpinner } semantics (hide is idempotent).
     */
    function runAsyncSubmit(button, label, workFn) {
        try {
            tryShowSpinner(button, label);
        } catch (e) {
            hideSpinner(button);
            return Promise.reject(e);
        }
        var p = Promise.resolve().then(workFn);
        return p
            .catch(function (err) {
                hideSpinner(button);
                throw err;
            })
            .finally(function () {
                hideSpinner(button);
            });
    }

    document.addEventListener(
        "submit",
        function (e) {
            var form = e.target;
            if (!isAuthForm(form)) {
                return;
            }

            var btn = getSubmitButton(form, e.submitter);
            if (!btn || btn.disabled) {
                return;
            }

            if (typeof form.checkValidity === "function" && !form.checkValidity()) {
                if (typeof form.reportValidity === "function") {
                    form.reportValidity();
                }
                return;
            }

            var label = getSubmitLabel(form);
            tryShowSpinner(btn, label);
        },
        true
    );

    document.addEventListener(
        "invalid",
        function (e) {
            var target = e.target;
            if (!target || !target.form) {
                return;
            }
            var form = target.form;
            if (!isAuthForm(form)) {
                return;
            }
            hideSpinner(getSubmitButton(form, null));
        },
        true
    );

    function onAuthFieldActivity(e) {
        var field = e.target;
        if (!field || !field.form || field.tagName === "BUTTON") {
            return;
        }
        var form = field.form;
        if (!isAuthForm(form)) {
            return;
        }
        hideSpinner(getSubmitButton(form, null));
    }

    document.addEventListener("input", onAuthFieldActivity, true);
    document.addEventListener("change", onAuthFieldActivity, true);

    window.addEventListener("pageshow", function (event) {
        if (!event.persisted) {
            return;
        }
        document.querySelectorAll("button.auth-submit-loading").forEach(function (btn) {
            hideSpinner(btn);
        });
    });

    window.authFormLoading = {
        showSpinner: tryShowSpinner,
        hideSpinner: hideSpinner,
        runAsyncSubmit: runAsyncSubmit,
    };
})();
