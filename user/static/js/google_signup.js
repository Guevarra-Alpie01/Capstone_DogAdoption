(function () {
    const form = document.querySelector("[data-google-signup-form]");
    if (!form) {
        return;
    }

    const googleClientId = (form.dataset.googleClientId || "").trim();
    const credentialInput = form.querySelector('input[name="google_credential"]');
    const buttonTarget = form.querySelector("[data-google-signup-button]");
    const errorOutput = form.querySelector("[data-google-signup-error]");

    function setError(message) {
        if (!errorOutput) {
            return;
        }
        errorOutput.textContent = message || "";
        errorOutput.classList.toggle("d-none", !message);
    }

    function clearError() {
        setError("");
    }

    form.addEventListener("submit", function (event) {
        if (credentialInput && credentialInput.value) {
            return;
        }
        if (!form.reportValidity()) {
            return;
        }
        event.preventDefault();
        setError("Continue with Google to finish creating your account.");
    });

    if (!buttonTarget) {
        return;
    }

    if (!googleClientId) {
        setError("Google signup is not configured yet. Please contact the administrator.");
        return;
    }

    if (!window.google || !window.google.accounts || !window.google.accounts.id) {
        setError("Google signup is temporarily unavailable. Refresh and try again.");
        return;
    }

    window.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: function (response) {
            clearError();
            if (!form.reportValidity()) {
                setError("Complete the required fields, then continue with Google again.");
                return;
            }
            if (!response || !response.credential || !credentialInput) {
                setError("Google could not confirm your account. Please try again.");
                return;
            }
            credentialInput.value = response.credential;
            form.submit();
        },
        auto_select: false,
        cancel_on_tap_outside: true,
        ux_mode: "popup",
    });

    window.google.accounts.id.renderButton(buttonTarget, {
        type: "standard",
        theme: "outline",
        size: "large",
        text: "continue_with",
        shape: "rectangular",
        logo_alignment: "left",
    });
})();
