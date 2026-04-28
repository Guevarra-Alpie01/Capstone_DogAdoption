(function () {
    function getSubmitButton(form, submitter) {
        if (submitter && submitter.matches && submitter.matches('button[type="submit"]')) {
            return submitter;
        }
        return form.querySelector('button[type="submit"]');
    }

    function applyLoading(button, label) {
        if (!button || button.dataset.authLoadingActive === "1") {
            return;
        }
        button.dataset.authLoadingActive = "1";
        button.dataset.authLoadingOriginal = button.innerHTML;
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        button.classList.add("auth-submit-loading");
        button.innerHTML =
            '<span class="auth-btn-loading-spinner" aria-hidden="true"></span>' +
            '<span class="auth-btn-loading-label">' +
            label +
            "</span>";
    }

    document.addEventListener(
        "submit",
        function (e) {
            var form = e.target;
            if (!form || form.tagName !== "FORM") {
                return;
            }

            if (!form.classList.contains("signup-form")) {
                return;
            }

            var label = "Creating...";

            var btn = getSubmitButton(form, e.submitter);
            if (!btn || btn.disabled) {
                return;
            }

            applyLoading(btn, label);
        },
        true
    );
})();
