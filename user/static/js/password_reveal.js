(function () {
    function setVisibility(button, visible) {
        const targetId = button.getAttribute("data-password-toggle");
        const input = targetId ? document.getElementById(targetId) : null;
        if (!input) return;
        input.type = visible ? "text" : "password";
        const icon = button.querySelector("i");
        if (icon) {
            icon.className = visible ? "bi bi-eye-slash" : "bi bi-eye";
        }
        button.setAttribute("aria-pressed", visible ? "true" : "false");
    }

    document.addEventListener("DOMContentLoaded", function () {
        const toggles = document.querySelectorAll(".password-toggle[data-password-toggle]");
        toggles.forEach((button) => {
            let locked = false;

            // Hover/press to reveal while interacting.
            button.addEventListener("mouseenter", function () {
                if (!locked) setVisibility(button, true);
            });
            button.addEventListener("mouseleave", function () {
                if (!locked) setVisibility(button, false);
            });
            button.addEventListener("mousedown", function (e) {
                e.preventDefault();
                if (!locked) setVisibility(button, true);
            });
            button.addEventListener("mouseup", function () {
                if (!locked) setVisibility(button, false);
            });
            button.addEventListener("touchstart", function () {
                if (!locked) setVisibility(button, true);
            }, { passive: true });
            button.addEventListener("touchend", function () {
                if (!locked) setVisibility(button, false);
            }, { passive: true });
            button.addEventListener("blur", function () {
                if (!locked) setVisibility(button, false);
            });

            // Click fallback for accessibility.
            button.addEventListener("click", function (e) {
                e.preventDefault();
                locked = !locked;
                setVisibility(button, locked);
            });
        });
    });
})();
