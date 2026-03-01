(function () {
    const listCache = new Map();

    function cleanInput(value) {
        return (value || "").replace(/\s+/g, " ").trim();
    }

    function normalizeText(value) {
        return cleanInput(value).toLowerCase().replace(/[^a-z0-9]/g, "");
    }

    async function fetchBarangays(sourceUrl) {
        if (!sourceUrl) {
            return [];
        }
        if (listCache.has(sourceUrl)) {
            return listCache.get(sourceUrl);
        }
        try {
            const response = await fetch(sourceUrl, { credentials: "same-origin" });
            if (!response.ok) {
                return [];
            }
            const payload = await response.json();
            const list = Array.isArray(payload.barangays) ? payload.barangays : [];
            listCache.set(sourceUrl, list);
            return list;
        } catch (e) {
            return [];
        }
    }

    function findExact(items, value) {
        const normalized = normalizeText(value);
        if (!normalized) {
            return "";
        }
        return items.find((item) => normalizeText(item) === normalized) || "";
    }

    function findMatches(items, value) {
        const normalized = normalizeText(value);
        if (!normalized) {
            return [];
        }
        return items.filter((item) => normalizeText(item).includes(normalized));
    }

    function hideSuggestions(box) {
        if (!box) {
            return;
        }
        box.style.display = "none";
        box.innerHTML = "";
    }

    function initInput(input) {
        const sourceUrl = input.dataset.barangaySourceUrl || "";
        const strictMode = input.dataset.barangayStrict === "true";
        const suggestionsId = input.dataset.barangaySuggestionsId || "";
        const suggestionsBox = suggestionsId ? document.getElementById(suggestionsId) : null;
        const parentForm = input.form;

        if (!sourceUrl || !suggestionsBox) {
            return;
        }

        function selectValue(value) {
            input.value = value;
            input.setCustomValidity("");
            hideSuggestions(suggestionsBox);
        }

        function renderSuggestions(matches) {
            if (!matches.length) {
                hideSuggestions(suggestionsBox);
                return;
            }
            suggestionsBox.innerHTML = "";
            matches.forEach((value) => {
                const item = document.createElement("div");
                item.className = "suggestion-item";
                item.dataset.value = value;
                item.textContent = value;
                suggestionsBox.appendChild(item);
            });
            suggestionsBox.style.display = "block";
        }

        async function normalizeField() {
            const list = await fetchBarangays(sourceUrl);
            const cleaned = cleanInput(input.value);
            const exact = findExact(list, cleaned);
            input.value = exact || cleaned;
            if (exact || !cleaned) {
                input.setCustomValidity("");
            }
            return Boolean(exact);
        }

        async function searchAndSelect() {
            const list = await fetchBarangays(sourceUrl);
            const cleaned = cleanInput(input.value);
            const exact = findExact(list, cleaned);
            const matches = findMatches(list, cleaned);
            if (exact) {
                selectValue(exact);
                return;
            }
            if (matches.length) {
                selectValue(matches[0]);
                return;
            }
            input.value = cleaned;
            renderSuggestions(matches);
        }

        input.addEventListener("input", async (e) => {
            input.setCustomValidity("");
            const list = await fetchBarangays(sourceUrl);
            const cleaned = cleanInput(e.target.value);
            input.value = cleaned;
            if (!normalizeText(cleaned)) {
                hideSuggestions(suggestionsBox);
                return;
            }
            renderSuggestions(findMatches(list, cleaned));
        });

        input.addEventListener("blur", () => normalizeField());
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                searchAndSelect();
            }
        });

        if (parentForm) {
            parentForm.addEventListener("submit", async (e) => {
                const ok = await normalizeField();
                hideSuggestions(suggestionsBox);
                if (strictMode) {
                    const hasValue = Boolean(cleanInput(input.value));
                    const shouldEnforce = input.required || hasValue;
                    if (shouldEnforce && !ok) {
                        e.preventDefault();
                        input.setCustomValidity("Please choose a barangay from the suggestions.");
                        input.reportValidity();
                    }
                }
            });
        }

        suggestionsBox.addEventListener("click", (e) => {
            const target = e.target.closest(".suggestion-item");
            if (target && target.dataset.value) {
                selectValue(target.dataset.value);
            }
        });

        document.addEventListener("click", (e) => {
            if (!suggestionsBox.contains(e.target) && e.target !== input) {
                hideSuggestions(suggestionsBox);
            }
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        const inputs = document.querySelectorAll("[data-barangay-autocomplete='true']");
        inputs.forEach((input) => initInput(input));
    });
})();
