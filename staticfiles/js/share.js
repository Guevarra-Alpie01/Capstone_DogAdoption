/**
 * Shared share utility — used by adopt_list, missing_dogs, and any future page.
 *
 * Buttons opt in with:
 *   data-finder-share
 *   data-share-url="..."          (absolute or relative URL to share)
 *   data-share-title="..."        (optional — Web Share API title)
 *   data-share-text="..."         (optional — Web Share API body text)
 *
 * An optional child element with [data-finder-share-label] has its text swapped
 * to "Shared" / "Link Copied" for 1.8 s then restored.
 *
 * A live-region element with id="finderShareStatus" (if present) receives
 * screen-reader announcements.
 */
(function () {
    'use strict';

    function getShareStatus() {
        return document.getElementById('finderShareStatus');
    }

    function announceShareStatus(message) {
        var el = getShareStatus();
        if (!el) return;
        el.textContent = '';
        window.setTimeout(function () { el.textContent = message; }, 20);
    }

    function setShareFeedback(button, message) {
        if (!button) return;
        var label = button.querySelector('[data-finder-share-label]');
        var originalLabel = button.getAttribute('data-original-label') ||
            (label ? label.textContent : 'Share');

        if (!button.hasAttribute('data-original-label')) {
            button.setAttribute('data-original-label', originalLabel);
        }
        if (label) label.textContent = message;
        button.classList.add('is-shared');

        if (button.dataset.shareTimerId) {
            window.clearTimeout(Number(button.dataset.shareTimerId));
        }
        button.dataset.shareTimerId = String(window.setTimeout(function () {
            if (label) label.textContent = originalLabel;
            button.classList.remove('is-shared');
            delete button.dataset.shareTimerId;
        }, 1800));
    }

    async function shareFinderCard(button) {
        var rawUrl = button.getAttribute('data-share-url') || window.location.pathname;
        var shareUrl = new URL(rawUrl, window.location.origin).href;
        var shareTitle = button.getAttribute('data-share-title') || 'Bayawan Vet dog listing';
        var shareText = button.getAttribute('data-share-text') ||
            ('See ' + shareTitle + ' on Bayawan Vet.');

        if (navigator.share) {
            try {
                await navigator.share({ title: shareTitle, text: shareText, url: shareUrl });
                setShareFeedback(button, 'Shared');
                announceShareStatus('Share sheet opened.');
                return;
            } catch (err) {
                if (err && err.name === 'AbortError') return;
            }
        }

        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(shareUrl);
                setShareFeedback(button, 'Link Copied');
                announceShareStatus('Dog link copied to clipboard.');
                return;
            } catch (_) { /* fall through */ }
        }

        /* Textarea fallback */
        var ta = document.createElement('textarea');
        ta.value = shareUrl;
        ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try {
            document.execCommand('copy');
            setShareFeedback(button, 'Link Copied');
            announceShareStatus('Dog link copied to clipboard.');
        } catch (_) {
            var shareWindow = window.open(
                'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(shareUrl),
                '_blank', 'noopener,noreferrer'
            );
            if (shareWindow) {
                setShareFeedback(button, 'Sharing');
                announceShareStatus('Social share opened in a new tab.');
            }
        }
        document.body.removeChild(ta);
    }

    /* Attach to all [data-finder-share] buttons, now and on future DOM mutations */
    function attachShareButtons(root) {
        var scope = (root && root.querySelectorAll) ? root : document;
        scope.querySelectorAll('[data-finder-share]:not([data-share-ready])').forEach(function (btn) {
            btn.setAttribute('data-share-ready', '1');
            btn.addEventListener('click', function () { shareFinderCard(btn); });
        });
    }

    /* Expose for pages that render content dynamically */
    window.attachShareButtons = attachShareButtons;
    window.shareFinderCard    = shareFinderCard;

    document.addEventListener('DOMContentLoaded', function () {
        attachShareButtons(document);
    });
})();
