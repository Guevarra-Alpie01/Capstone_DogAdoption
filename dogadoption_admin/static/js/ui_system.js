(function () {
    "use strict";

    function getFieldLabel(field) {
        if (field.dataset && field.dataset.label) {
            return field.dataset.label;
        }

        var id = field.getAttribute("id");
        if (id) {
            var labels = document.querySelectorAll("label");
            for (var i = 0; i < labels.length; i += 1) {
                if (labels[i].htmlFor === id) {
                    return labels[i].textContent.trim();
                }
            }
        }

        if (field.getAttribute("aria-label")) {
            return field.getAttribute("aria-label");
        }

        if (field.getAttribute("name")) {
            return field.getAttribute("name").replace(/_/g, " ");
        }

        return "This field";
    }

    function showSummary(form, invalidFields) {
        var summary = form.querySelector(".form-error-summary");
        if (!summary) {
            return;
        }

        var limited = invalidFields.slice(0, 6);
        var listItems = limited.map(function (field) {
            return "<li><strong>" + getFieldLabel(field) + "</strong>: " + field.validationMessage + "</li>";
        }).join("");

        var heading = "Please review the highlighted fields before submitting.";
        summary.innerHTML = "<p><strong>" + heading + "</strong></p><ul>" + listItems + "</ul>";
        summary.hidden = false;
        summary.setAttribute("tabindex", "-1");
        summary.focus();
    }

    function clearSummary(form) {
        var summary = form.querySelector(".form-error-summary");
        if (summary) {
            summary.hidden = true;
            summary.innerHTML = "";
        }
    }

    function applyValidation(form) {
        var submitButtons = form.querySelectorAll('button[type="submit"], input[type="submit"]');

        form.addEventListener("submit", function (event) {
            var isValid = form.checkValidity();

            if (!isValid) {
                event.preventDefault();
                form.classList.add("was-validated");

                var invalidFields = Array.prototype.filter.call(
                    form.querySelectorAll(":invalid"),
                    function (field) {
                        return field.type !== "hidden";
                    }
                );

                invalidFields.forEach(function (field) {
                    field.classList.add("is-invalid");
                    field.setAttribute("aria-invalid", "true");
                });

                showSummary(form, invalidFields);

                if (invalidFields.length > 0) {
                    invalidFields[0].focus();
                }
                return;
            }

            clearSummary(form);

            if (form.dataset.disableSubmit === "true") {
                if (form.dataset.submitting === "true") {
                    event.preventDefault();
                    return;
                }

                form.dataset.submitting = "true";
                submitButtons.forEach(function (button) {
                    button.disabled = true;
                    var loadingText = button.getAttribute("data-loading-text");
                    if (loadingText) {
                        button.setAttribute("data-original-text", button.textContent);
                        button.textContent = loadingText;
                    }
                });
            }
        });

        form.querySelectorAll("input, select, textarea").forEach(function (field) {
            field.addEventListener("input", function () {
                if (field.checkValidity()) {
                    field.classList.remove("is-invalid");
                    field.removeAttribute("aria-invalid");
                }
            });
        });
    }

    function autoDismissAlerts() {
        document.querySelectorAll(".ui-alert[data-auto-dismiss='true']").forEach(function (alert) {
            window.setTimeout(function () {
                alert.style.opacity = "0";
                alert.style.transform = "translateY(-4px)";
                window.setTimeout(function () {
                    alert.remove();
                }, 220);
            }, 4200);
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("form.js-validate").forEach(function (form) {
            applyValidation(form);
        });

        autoDismissAlerts();
    });
})();

