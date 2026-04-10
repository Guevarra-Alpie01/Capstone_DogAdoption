(function () {
    function initSharedConfirmModal() {
        const confirmModalEl = document.getElementById("sharedConfirmModal");
        const confirmTitleEl = document.getElementById("sharedConfirmModalTitle");
        const confirmMessageEl = document.getElementById("sharedConfirmModalMessage");
        const confirmSubmitBtn = document.getElementById("sharedConfirmModalSubmit");

        if (!confirmModalEl || !confirmSubmitBtn || !window.bootstrap || !window.bootstrap.Modal) {
            return;
        }

        const confirmModal = window.bootstrap.Modal.getOrCreateInstance(confirmModalEl);
        const defaultSubmitClass = confirmSubmitBtn.className || "btn btn-primary";
        const defaultTitle = confirmTitleEl ? confirmTitleEl.textContent : "Confirm Action";
        const defaultMessage = confirmMessageEl ? confirmMessageEl.textContent : "Please confirm to continue.";
        const defaultSubmitLabel = confirmSubmitBtn.textContent || "OK";
        let pendingForm = null;
        let pendingButton = null;
        let pendingCallback = null;

        function findOwnerForm(source) {
            if (!source) {
                return null;
            }

            if (source.tagName === "FORM") {
                return source;
            }

            if (source.form) {
                return source.form;
            }

            if (typeof source.closest === "function") {
                return source.closest("form");
            }

            return null;
        }

        function readConfirmValue(source, key) {
            if (!source) {
                return "";
            }

            if (source.dataset && source.dataset[key]) {
                return source.dataset[key];
            }

            const ownerForm = findOwnerForm(source);
            if (ownerForm && ownerForm !== source && ownerForm.dataset && ownerForm.dataset[key]) {
                return ownerForm.dataset[key];
            }

            return "";
        }

        function applyConfirmConfig(config) {
            if (confirmTitleEl) {
                confirmTitleEl.textContent = config.title || defaultTitle;
            }

            if (confirmMessageEl) {
                confirmMessageEl.textContent = config.message || defaultMessage;
            }

            confirmSubmitBtn.textContent = config.submitLabel || defaultSubmitLabel;
            confirmSubmitBtn.className = config.submitClass || defaultSubmitClass;
        }

        function buildConfirmConfig(source, overrides) {
            const config = overrides || {};
            return {
                title: config.title || readConfirmValue(source, "confirmTitle") || defaultTitle,
                message:
                    config.message ||
                    readConfirmValue(source, "confirmMessage") ||
                    readConfirmValue(source, "confirmBody") ||
                    defaultMessage,
                submitLabel: config.submitLabel || readConfirmValue(source, "confirmSubmitLabel") || defaultSubmitLabel,
                submitClass: config.submitClass || readConfirmValue(source, "confirmSubmitClass") || defaultSubmitClass,
            };
        }

        function clearPendingState() {
            pendingForm = null;
            pendingButton = null;
            pendingCallback = null;
            confirmSubmitBtn.textContent = defaultSubmitLabel;
            confirmSubmitBtn.className = defaultSubmitClass;
        }

        function openSharedConfirm(source, overrides) {
            applyConfirmConfig(buildConfirmConfig(source, overrides));
            confirmModal.show();
        }

        function isSubmitButton(button) {
            if (!button || button.tagName !== "BUTTON") {
                return false;
            }

            const type = (button.getAttribute("type") || "submit").toLowerCase();
            return type === "submit";
        }

        window.appSharedConfirm = {
            open: function (options) {
                pendingForm = null;
                pendingButton = null;
                pendingCallback = options && typeof options.onConfirm === "function" ? options.onConfirm : null;
                openSharedConfirm(null, options || {});
            },
            close: function () {
                confirmModal.hide();
            },
        };

        document.addEventListener(
            "submit",
            function (event) {
                const form = event.target;
                if (!(form instanceof HTMLFormElement) || !form.matches("[data-confirm-modal]")) {
                    return;
                }

                if (form.dataset.confirmedSubmit === "1") {
                    form.dataset.confirmedSubmit = "0";
                    return;
                }

                event.preventDefault();
                pendingForm = form;
                pendingButton = null;
                pendingCallback = null;
                openSharedConfirm(form);
            },
            true
        );

        document.addEventListener(
            "click",
            function (event) {
                const button = event.target instanceof Element ? event.target.closest("[data-confirm-button]") : null;
                if (!button || button.disabled) {
                    return;
                }

                const ownerForm = findOwnerForm(button);
                if (ownerForm && isSubmitButton(button) && typeof ownerForm.reportValidity === "function" && !ownerForm.reportValidity()) {
                    return;
                }

                event.preventDefault();
                pendingForm = null;
                pendingButton = button;
                pendingCallback = null;
                openSharedConfirm(button);
            },
            true
        );

        confirmSubmitBtn.addEventListener("click", function () {
            if (pendingCallback) {
                const callback = pendingCallback;
                clearPendingState();
                confirmModal.hide();
                callback();
                return;
            }

            if (pendingButton) {
                const buttonToSubmit = pendingButton;
                const targetForm = findOwnerForm(buttonToSubmit);
                clearPendingState();
                confirmModal.hide();

                if (targetForm) {
                    targetForm.dataset.confirmedSubmit = "1";
                    if (typeof targetForm.requestSubmit === "function") {
                        if (isSubmitButton(buttonToSubmit)) {
                            targetForm.requestSubmit(buttonToSubmit);
                        } else {
                            targetForm.requestSubmit();
                        }
                    } else {
                        targetForm.submit();
                    }
                    return;
                }

                if (buttonToSubmit.tagName === "A" && buttonToSubmit.href) {
                    window.location.assign(buttonToSubmit.href);
                }
                return;
            }

            if (!pendingForm) {
                return;
            }

            const formToSubmit = pendingForm;
            clearPendingState();
            confirmModal.hide();
            formToSubmit.dataset.confirmedSubmit = "1";

            if (typeof formToSubmit.requestSubmit === "function") {
                formToSubmit.requestSubmit();
                return;
            }

            formToSubmit.submit();
        });

        confirmModalEl.addEventListener("hidden.bs.modal", clearPendingState);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initSharedConfirmModal, { once: true });
    } else {
        initSharedConfirmModal();
    }
})();
