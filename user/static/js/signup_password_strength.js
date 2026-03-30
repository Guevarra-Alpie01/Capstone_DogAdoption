(function () {
    function collectRules(password) {
        return {
            length: password.length >= 8,
            upper: /[A-Z]/.test(password),
            lower: /[a-z]/.test(password),
            number: /\d/.test(password),
            symbol: /[^A-Za-z0-9]/.test(password),
        };
    }

    function resolveStrength(password) {
        const rules = collectRules(password);
        const metCount = Object.values(rules).filter(Boolean).length;

        if (!password) {
            return {
                label: "Not checked",
                tone: "is-empty",
                width: 0,
                rules,
            };
        }

        if (metCount <= 2) {
            return {
                label: "Weak",
                tone: "is-weak",
                width: Math.max(24, metCount * 20),
                rules,
            };
        }

        if (metCount < 5 || password.length < 10) {
            return {
                label: "Medium",
                tone: "is-medium",
                width: Math.max(58, metCount * 20),
                rules,
            };
        }

        return {
            label: "Strong",
            tone: "is-strong",
            width: 100,
            rules,
        };
    }

    function bindPasswordStrength(guide) {
        if (!guide || guide.dataset.passwordStrengthBound === "1") {
            return;
        }

        const inputId = guide.getAttribute("data-password-input-id");
        const input = inputId ? document.getElementById(inputId) : null;
        if (!input) {
            return;
        }

        const inputGroup = input.closest(".input-group");
        const status = guide.querySelector("[data-password-strength-status]");
        const fill = guide.querySelector("[data-password-strength-fill]");
        const ruleItems = guide.querySelectorAll("[data-password-rule]");

        function showGuide() {
            guide.classList.add("is-visible");
        }

        function hideGuide() {
            guide.classList.remove("is-visible");
        }

        function render() {
            const password = input.value || "";
            const strength = resolveStrength(password);

            if (status) {
                status.textContent = strength.label;
                status.className = "signup-password-strength-value " + strength.tone;
            }

            if (fill) {
                fill.style.width = strength.width + "%";
            }

            ruleItems.forEach(function (item) {
                const ruleKey = item.getAttribute("data-password-rule");
                item.classList.toggle("is-met", !!strength.rules[ruleKey]);
            });
        }

        function handleDocumentFocus(event) {
            const target = event.target;
            if (!target) {
                return;
            }

            const withinPasswordField = target === input
                || guide.contains(target)
                || (inputGroup && inputGroup.contains(target));

            if (withinPasswordField) {
                showGuide();
                return;
            }

            if (target.matches && target.matches("input, select, textarea, button")) {
                hideGuide();
            }
        }

        guide.dataset.passwordStrengthBound = "1";
        input.addEventListener("focus", showGuide);
        input.addEventListener("click", showGuide);
        if (inputGroup) {
            inputGroup.addEventListener("click", function (event) {
                if (event.target && event.target.closest(".password-toggle")) {
                    showGuide();
                }
            });
        }
        input.addEventListener("input", render);
        input.addEventListener("change", render);
        input.addEventListener("blur", render);
        document.addEventListener("focusin", handleDocumentFocus);

        render();
        hideGuide();
        window.setTimeout(render, 150);
    }

    function initPasswordStrengthGuides() {
        document.querySelectorAll("[data-password-strength]").forEach(bindPasswordStrength);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initPasswordStrengthGuides);
    } else {
        initPasswordStrengthGuides();
    }
})();
