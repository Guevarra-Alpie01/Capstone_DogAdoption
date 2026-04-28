/**
 * Load registration-style owner profile into a Bootstrap modal (post board + request pages).
 * Expects window.__postBoardProfileModalConfig from the host template.
 */
(function () {
    function getBootstrapModal(el) {
        if (!el || !window.bootstrap || !window.bootstrap.Modal || typeof window.bootstrap.Modal.getOrCreateInstance !== "function") {
            return null;
        }
        try {
            return window.bootstrap.Modal.getOrCreateInstance(el);
        } catch (e) {
            return null;
        }
    }

    function initPostBoardProfileModal(config) {
        var urlTemplate = config.urlTemplate || "";
        var placeholder = String(config.placeholder || "900000001");
        if (!urlTemplate || urlTemplate.indexOf(placeholder) === -1) {
            return;
        }

        var bodyEl = document.getElementById(config.bodyId || "postBoardUserProfileModalBody");
        var modalEl = document.getElementById(config.profileModalId || "postBoardUserProfileModal");
        var photoModalEl = document.getElementById(config.photoModalId || "postBoardOwnerPhotoViewerModal");
        var photoImg = document.getElementById(config.photoImageId || "postBoardOwnerPhotoViewerImage");
        var photoTitle = document.getElementById(config.photoTitleId || "postBoardOwnerPhotoViewerTitle");

        if (!bodyEl || !modalEl) {
            return;
        }

        var profileModal = getBootstrapModal(modalEl);
        var photoModal = photoModalEl ? getBootstrapModal(photoModalEl) : null;

        function buildUrl(userId) {
            return urlTemplate.replace(placeholder, String(userId));
        }

        function openPhoto(source, alt) {
            if (!photoModal || !photoImg || !source) {
                return;
            }
            photoImg.setAttribute("src", source);
            photoImg.setAttribute("alt", alt || "Preview photo");
            if (photoTitle) {
                photoTitle.textContent = alt || "Preview photo";
            }
            photoModal.show();
        }

        function bindPhotoHandlers(root) {
            if (!root) {
                return;
            }
            root.querySelectorAll(".js-owner-profile-avatar").forEach(function (btn) {
                if (btn.disabled) {
                    return;
                }
                btn.addEventListener("click", function () {
                    openPhoto(
                        btn.getAttribute("data-image-src") || "",
                        btn.getAttribute("data-image-alt") || "Profile photo"
                    );
                });
            });
            root.querySelectorAll(".js-owner-preview-photo").forEach(function (img) {
                img.addEventListener("click", function () {
                    openPhoto(img.getAttribute("src") || "", img.getAttribute("alt") || "Preview photo");
                });
            });
        }

        function loadProfile(userId) {
            bodyEl.innerHTML = '<div class="p-3 text-muted">Loading…</div>';
            if (profileModal) {
                profileModal.show();
            }
            fetch(buildUrl(userId), {
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            })
                .then(function (r) {
                    if (!r.ok) {
                        throw new Error("bad response");
                    }
                    return r.text();
                })
                .then(function (html) {
                    bodyEl.innerHTML = html;
                    bindPhotoHandlers(bodyEl);
                })
                .catch(function () {
                    bodyEl.innerHTML =
                        '<p class="text-danger mb-0 px-2 py-3">Could not load profile. Try again or open the full registration profile.</p>';
                });
        }

        document.addEventListener("click", function (e) {
            var trigger = e.target.closest("[data-post-board-user-id]");
            if (!trigger) {
                return;
            }
            var raw = trigger.getAttribute("data-post-board-user-id");
            var uid = parseInt(raw, 10);
            if (!uid || uid <= 0) {
                return;
            }
            e.preventDefault();
            loadProfile(uid);
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        if (window.__postBoardProfileModalConfig) {
            initPostBoardProfileModal(window.__postBoardProfileModalConfig);
        }
    });
})();
