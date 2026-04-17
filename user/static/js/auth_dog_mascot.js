(function () {
    "use strict";

    function isFormField(el) {
        if (!el || !el.matches) {
            return false;
        }
        return el.matches(
            "input:not([type=\"hidden\"]):not([type=\"button\"]):not([type=\"submit\"]):not([type=\"reset\"]), textarea, select"
        );
    }

    function initStack(stack) {
        var form = stack.querySelector("form");
        if (!form) {
            return;
        }

        function setFocused(on) {
            stack.classList.toggle("is-field-focused", on);
        }

        form.addEventListener("focusin", function (e) {
            if (isFormField(e.target)) {
                setFocused(true);
            }
        });

        form.addEventListener("focusout", function () {
            window.requestAnimationFrame(function () {
                var active = document.activeElement;
                if (!form.contains(active) || !isFormField(active)) {
                    setFocused(false);
                }
            });
        });
    }

    function init() {
        document.querySelectorAll("[data-auth-dog-stack]").forEach(initStack);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
