/**
 * Admin analytics dashboard — 3D Plotly charts driven by the same JSON payloads
 * and filter DOM as the legacy Chart.js implementation.
 */
(function () {
    "use strict";

    const D = window.AnalyticsDashboard || {};
    const monthLabels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const piePalette = ["#2563eb", "#0f766e", "#f97316", "#be123c", "#7c3aed", "#0891b2", "#ca8a04", "#4f46e5", "#15803d"];
    const linePalette = ["#2563eb", "#dc2626", "#16a34a", "#7c3aed", "#ea580c", "#0891b2", "#be123c", "#4f46e5", "#0f766e", "#9333ea"];

    const analyticsPhoneMediaQuery = window.matchMedia("(max-width: 575.98px)");
    const analyticsTinyPhoneMediaQuery = window.matchMedia("(max-width: 414.98px)");
    const isAnalyticsPhone = () => analyticsPhoneMediaQuery.matches;
    const isAnalyticsTinyPhone = () => analyticsTinyPhoneMediaQuery.matches;

    const analyticsSeriesColor = (idx, palette = linePalette) => palette[idx] || `hsl(${(idx * 47) % 360} 72% 45%)`;

    const analyticsViewportBucket = () => {
        if (window.innerWidth <= 414.98) return "tiny-phone";
        if (window.innerWidth <= 575.98) return "phone";
        if (window.innerWidth <= 767.98) return "small-tablet";
        if (window.innerWidth <= 1199.98) return "tablet";
        return "desktop";
    };

    let lastAnalyticsViewportBucket = analyticsViewportBucket();
    let analyticsRefreshTimeoutId = null;
    const analyticsPlotElements = [];
    const analyticsRenderers = [];

    const registerAnalyticsPlotElement = (el) => {
        if (el && !analyticsPlotElements.includes(el)) {
            analyticsPlotElements.push(el);
        }
    };

    const registerAnalyticsRenderer = (renderFn) => {
        analyticsRenderers.push(renderFn);
    };

    const resizeAnalyticsPlots = () => {
        if (typeof Plotly === "undefined") return;
        analyticsPlotElements.forEach((el) => {
            if (el && el.offsetParent !== null) {
                try {
                    Plotly.Plots.resize(el);
                } catch (_e) {
                    /* ignore */
                }
            }
        });
    };

    const scheduleAnalyticsRefresh = () => {
        window.clearTimeout(analyticsRefreshTimeoutId);
        analyticsRefreshTimeoutId = window.setTimeout(() => {
            const nextBucket = analyticsViewportBucket();
            if (nextBucket !== lastAnalyticsViewportBucket) {
                lastAnalyticsViewportBucket = nextBucket;
                analyticsRenderers.forEach((renderFn) => renderFn());
            } else {
                resizeAnalyticsPlots();
            }
        }, 120);
    };

    const safePurge = (el) => {
        if (!el || typeof Plotly === "undefined") return;
        try {
            Plotly.purge(el);
        } catch (_e) {
            /* ignore */
        }
    };

    const plotlyConfig = () => ({
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
        scrollZoom: true,
    });

    const sceneAxes = () => ({
        showbackground: false,
        gridcolor: "rgba(148, 163, 184, 0.22)",
        zerolinecolor: "rgba(148, 163, 184, 0.35)",
        color: "#64748b",
        showspikes: false,
    });

    const layout3d = (sceneOverrides = {}) => {
        const {
            xaxis: xExtra,
            yaxis: yExtra,
            zaxis: zExtra,
            camera,
            aspectmode,
            ...restScene
        } = sceneOverrides || {};
        return {
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(0,0,0,0)",
            margin: { l: 0, r: 0, t: 8, b: 0 },
            font: {
                color: "#475569",
                family: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
                size: isAnalyticsTinyPhone() ? 10 : isAnalyticsPhone() ? 10 : 11,
            },
            showlegend: false,
            scene: {
                xaxis: { ...sceneAxes(), ...xExtra },
                yaxis: { ...sceneAxes(), ...yExtra },
                zaxis: { ...sceneAxes(), ...zExtra },
                bgcolor: "rgba(0,0,0,0)",
                aspectmode: aspectmode || "data",
                camera: camera || { eye: { x: 1.5, y: 1.45, z: 1.05 } },
                ...restScene,
            },
        };
    };

    const layout3dLegend = (sceneOverrides = {}, legend = {}) => ({
        ...layout3d(sceneOverrides),
        showlegend: true,
        legend: {
            x: 0.02,
            y: 0.98,
            bgcolor: "rgba(255,255,255,0.42)",
            bordercolor: "rgba(148, 163, 184, 0.35)",
            borderwidth: 1,
            font: { size: isAnalyticsTinyPhone() ? 9 : 10, color: "#334155" },
            ...legend,
        },
    });

    function buildPillarRingTraces(labels, values, colors) {
        const n = labels.length;
        if (!n) return [];
        const total = values.reduce((a, b) => a + b, 0) || 1;
        const maxV = Math.max(...values, 1);
        const R = isAnalyticsPhone() ? 2.6 : 3.4;
        const lx = [];
        const ly = [];
        const lz = [];
        const xs = [];
        const ys = [];
        const zs = [];
        const text = [];
        const cols = [];
        const sizes = [];
        let cum = 0;
        for (let i = 0; i < n; i += 1) {
            const frac = values[i] / total;
            const mid = (cum + frac / 2) * 2 * Math.PI - Math.PI / 2;
            cum += frac;
            const x = R * Math.cos(mid);
            const y = R * Math.sin(mid);
            const z = (values[i] / maxV) * (isAnalyticsPhone() ? 3.2 : 4.2) + 0.25;
            lx.push(0, x, null);
            ly.push(0, y, null);
            lz.push(0, z, null);
            xs.push(x);
            ys.push(y);
            zs.push(z);
            text.push(`${labels[i]}<br><b>${values[i]}</b>`);
            cols.push(colors[i % colors.length]);
            sizes.push((isAnalyticsTinyPhone() ? 8 : isAnalyticsPhone() ? 9 : 10) + (values[i] / maxV) * (isAnalyticsPhone() ? 14 : 18));
        }
        const stems = {
            type: "scatter3d",
            mode: "lines",
            x: lx,
            y: ly,
            z: lz,
            line: { color: "rgba(148, 163, 184, 0.4)", width: isAnalyticsPhone() ? 2 : 3 },
            hoverinfo: "skip",
            showlegend: false,
        };
        const markers = {
            type: "scatter3d",
            mode: "markers",
            x: xs,
            y: ys,
            z: zs,
            text,
            hovertemplate: "%{text}<extra></extra>",
            marker: {
                size: sizes,
                color: cols,
                opacity: 0.94,
                line: { color: "#ffffff", width: 2 },
                sizemode: "diameter",
            },
            name: "Share",
        };
        return [stems, markers];
    }

    function mountPlot(el, traces, layout) {
        if (!el || typeof Plotly === "undefined") return;
        safePurge(el);
        Plotly.newPlot(el, traces, layout, plotlyConfig()).catch(() => {});
    }

    /* ---------- Vaccination breed ---------- */
    const vaccinationBreedData = D.vaccinationBreed || {};
    const vaccinationBreedYearFilter = document.getElementById("vaccinationBreedYearFilter");
    const vaccinationBreedViewFilter = document.getElementById("vaccinationBreedViewFilter");
    const vaccinationBreedMonthFilter = document.getElementById("vaccinationBreedMonthFilter");
    const vaccinationBreedTypeFilter = document.getElementById("vaccinationBreedTypeFilter");
    const vaccinationBreedEmptyState = document.getElementById("vaccinationBreedEmptyState");
    const vaccinationBreedEl = document.getElementById("vaccinationBreedChart");
    const vaccinationBreedRows = vaccinationBreedData.rows || [];
    const vaccinationBreedYears = (vaccinationBreedData.years || []).slice().sort((a, b) => a - b);
    const currentMonth = new Date().getMonth() + 1;

    const resolveVaccinationBreedDefaultYear = () => {
        const nowYear = new Date().getFullYear();
        if (vaccinationBreedYears.includes(nowYear)) return nowYear;
        return vaccinationBreedYears.length ? vaccinationBreedYears[vaccinationBreedYears.length - 1] : nowYear;
    };

    const selectedVaccinationBreedYearDefault = resolveVaccinationBreedDefaultYear();
    if (!vaccinationBreedYears.length) {
        vaccinationBreedYears.push(selectedVaccinationBreedYearDefault);
    }

    vaccinationBreedYears.forEach((year) => {
        const option = document.createElement("option");
        option.value = String(year);
        option.textContent = String(year);
        vaccinationBreedYearFilter.appendChild(option);
    });
    vaccinationBreedYearFilter.value = String(selectedVaccinationBreedYearDefault);
    vaccinationBreedMonthFilter.value = String(currentMonth);

    const buildVaccinationBreedPieData = (mode, year, month, animalType) => {
        const totalsByBreed = new Map();
        vaccinationBreedRows.forEach((row) => {
            const rowDate = new Date(`${row.date}T00:00:00`);
            if (Number.isNaN(rowDate.getTime())) return;
            if (rowDate.getFullYear() !== year) return;
            if (mode === "month" && rowDate.getMonth() + 1 !== month) return;
            if (animalType !== "all" && row.animal_type !== animalType) return;
            const breed = row.breed || "Unknown Breed";
            totalsByBreed.set(breed, (totalsByBreed.get(breed) || 0) + (Number(row.total) || 0));
        });
        const rankedBreeds = Array.from(totalsByBreed.entries())
            .map(([label, total]) => ({ label, total }))
            .sort((a, b) => b.total - a.total);
        const topBreeds = rankedBreeds.slice(0, 8);
        const otherTotal = rankedBreeds.slice(8).reduce((sum, entry) => sum + entry.total, 0);
        const labels = topBreeds.map((entry) => entry.label);
        const values = topBreeds.map((entry) => entry.total);
        if (otherTotal > 0) {
            labels.push("Other Breeds");
            values.push(otherTotal);
        }
        const colors = labels.map((_, idx) => piePalette[idx % piePalette.length]);
        return { labels, values, colors };
    };

    const renderVaccinationBreedChart = () => {
        const mode = vaccinationBreedViewFilter.value;
        const selectedYear = Number(vaccinationBreedYearFilter.value);
        const selectedMonth = Number(vaccinationBreedMonthFilter.value);
        const selectedType = vaccinationBreedTypeFilter.value;
        vaccinationBreedMonthFilter.style.display = mode === "month" ? "inline-flex" : "none";

        const pie = buildVaccinationBreedPieData(mode, selectedYear, selectedMonth, selectedType);
        const hasData = pie.labels.length > 0;
        vaccinationBreedEmptyState.hidden = hasData;

        if (!hasData) {
            safePurge(vaccinationBreedEl);
            return;
        }

        const traces = buildPillarRingTraces(pie.labels, pie.values, pie.colors);
        mountPlot(vaccinationBreedEl, traces, layout3d({ camera: { eye: { x: 1.55, y: 1.5, z: 1.12 } }, aspectmode: "cube" }));
    };

    /* ---------- Adoption / claim trend ---------- */
    const adoptionClaimTrendData = D.adoptionClaimTrend || {};
    const adoptionClaimTrendYearFilter = document.getElementById("adoptionClaimTrendYearFilter");
    const adoptionClaimTrendViewFilter = document.getElementById("adoptionClaimTrendViewFilter");
    const adoptionClaimTrendMonthFilter = document.getElementById("adoptionClaimTrendMonthFilter");
    const adoptionClaimTrendEmptyState = document.getElementById("adoptionClaimTrendEmptyState");
    const adoptionClaimTrendEl = document.getElementById("adoptionClaimTrendChart");
    const adoptionClaimRows = adoptionClaimTrendData.rows || [];
    const adoptionClaimYears = (adoptionClaimTrendData.years || []).slice().sort((a, b) => a - b);

    const resolveAdoptionClaimDefaultYear = () => {
        const nowYear = new Date().getFullYear();
        if (adoptionClaimYears.includes(nowYear)) return nowYear;
        return adoptionClaimYears.length ? adoptionClaimYears[adoptionClaimYears.length - 1] : nowYear;
    };

    const selectedAdoptionClaimYearDefault = resolveAdoptionClaimDefaultYear();
    if (!adoptionClaimYears.length) {
        adoptionClaimYears.push(selectedAdoptionClaimYearDefault);
    }

    adoptionClaimYears.forEach((year) => {
        const option = document.createElement("option");
        option.value = String(year);
        option.textContent = String(year);
        adoptionClaimTrendYearFilter.appendChild(option);
    });
    adoptionClaimTrendYearFilter.value = String(selectedAdoptionClaimYearDefault);
    adoptionClaimTrendMonthFilter.value = String(currentMonth);

    const buildAdoptionClaimTrendSeries = (mode, year, month) => {
        const labels =
            mode === "year"
                ? monthLabels
                : Array.from({ length: new Date(year, month, 0).getDate() }, (_, idx) => String(idx + 1));
        const adoptedData = Array(labels.length).fill(0);
        const claimedData = Array(labels.length).fill(0);
        adoptionClaimRows.forEach((row) => {
            const eventDate = new Date(`${row.date}T00:00:00`);
            if (Number.isNaN(eventDate.getTime())) return;
            if (eventDate.getFullYear() !== year) return;
            if (mode === "month" && eventDate.getMonth() + 1 !== month) return;
            const bucketIdx = mode === "year" ? eventDate.getMonth() : eventDate.getDate() - 1;
            const rowTotal = Number(row.total) || 0;
            if (row.status === "adopted") {
                adoptedData[bucketIdx] += rowTotal;
            } else {
                claimedData[bucketIdx] += rowTotal;
            }
        });
        return { labels, adoptedData, claimedData };
    };

    const renderAdoptionClaimTrendChart = () => {
        const mode = adoptionClaimTrendViewFilter.value;
        const selectedYear = Number(adoptionClaimTrendYearFilter.value);
        const selectedMonth = Number(adoptionClaimTrendMonthFilter.value);
        adoptionClaimTrendMonthFilter.style.display = mode === "month" ? "inline-flex" : "none";

        const { labels, adoptedData, claimedData } = buildAdoptionClaimTrendSeries(mode, selectedYear, selectedMonth);
        const hasData = adoptedData.some((v) => v > 0) || claimedData.some((v) => v > 0);
        adoptionClaimTrendEmptyState.hidden = hasData;
        if (!hasData) {
            safePurge(adoptionClaimTrendEl);
            return;
        }

        const xIdx = labels.map((_, i) => i);
        const zAdopted = xIdx.map(() => 0);
        const zClaimed = xIdx.map(() => (isAnalyticsPhone() ? 1.65 : 2.15));
        const mSize = isAnalyticsTinyPhone() ? 3 : isAnalyticsPhone() ? 3.5 : 4.5;

        const traces = [
            {
                type: "scatter3d",
                mode: "lines+markers",
                name: "Adopted",
                x: xIdx,
                y: adoptedData,
                z: zAdopted,
                customdata: labels,
                hovertemplate: "<b>Adopted</b><br>%{customdata}<br>Count: %{y}<extra></extra>",
                line: { color: "#be123c", width: isAnalyticsPhone() ? 4 : 6 },
                marker: { size: mSize, color: "#be123c", line: { color: "#fff", width: 1 } },
            },
            {
                type: "scatter3d",
                mode: "lines+markers",
                name: "Claimed",
                x: xIdx,
                y: claimedData,
                z: zClaimed,
                customdata: labels,
                hovertemplate: "<b>Claimed</b><br>%{customdata}<br>Count: %{y}<extra></extra>",
                line: { color: "#0f766e", width: isAnalyticsPhone() ? 4 : 6 },
                marker: { size: mSize, color: "#0f766e", line: { color: "#fff", width: 1 } },
            },
        ];

        const scene = {
            xaxis: { ...sceneAxes(), title: mode === "year" ? "Month index" : "Day of month" },
            yaxis: { ...sceneAxes(), title: "Count" },
            zaxis: { ...sceneAxes(), title: "", showticklabels: false },
            camera: { eye: { x: 1.35, y: 1.72, z: 0.85 } },
        };
        mountPlot(adoptionClaimTrendEl, traces, layout3dLegend(scene));
    };

    /* ---------- Rescue barangay trend ---------- */
    const rescueBarangayTrendData = D.rescueBarangayTrend || {};
    const rescueTrendYearFilter = document.getElementById("rescueTrendYearFilter");
    const rescueTrendViewFilter = document.getElementById("rescueTrendViewFilter");
    const rescueTrendMonthFilter = document.getElementById("rescueTrendMonthFilter");
    const rescueTrendEmptyState = document.getElementById("rescueTrendEmptyState");
    const rescueTrendEl = document.getElementById("rescueBarangayTrendChart");
    const rescueEvents = rescueBarangayTrendData.events || [];
    const rescueYears = (rescueBarangayTrendData.years || []).slice().sort((a, b) => a - b);

    const resolveRescueDefaultYear = () => {
        const nowYear = new Date().getFullYear();
        if (rescueYears.includes(nowYear)) return nowYear;
        return rescueYears.length ? rescueYears[rescueYears.length - 1] : nowYear;
    };

    const selectedRescueYearDefault = resolveRescueDefaultYear();
    if (!rescueYears.length) {
        rescueYears.push(selectedRescueYearDefault);
    }

    rescueYears.forEach((year) => {
        const option = document.createElement("option");
        option.value = String(year);
        option.textContent = String(year);
        rescueTrendYearFilter.appendChild(option);
    });
    rescueTrendYearFilter.value = String(selectedRescueYearDefault);
    rescueTrendMonthFilter.value = String(currentMonth);

    const buildRescueTrendSeries = (mode, year, month) => {
        const labels =
            mode === "year"
                ? monthLabels
                : Array.from({ length: new Date(year, month, 0).getDate() }, (_, idx) => String(idx + 1));
        const bucketCount = labels.length;
        const byBarangay = {};
        rescueEvents.forEach((event) => {
            const eventDate = new Date(`${event.date}T00:00:00`);
            if (Number.isNaN(eventDate.getTime())) return;
            if (eventDate.getFullYear() !== year) return;
            if (mode === "month" && eventDate.getMonth() + 1 !== month) return;
            const bucketIdx = mode === "year" ? eventDate.getMonth() : eventDate.getDate() - 1;
            const barangay = event.barangay || "Unknown";
            if (!byBarangay[barangay]) {
                byBarangay[barangay] = Array(bucketCount).fill(0);
            }
            byBarangay[barangay][bucketIdx] += 1;
        });
        const rankedBarangays = Object.entries(byBarangay)
            .map(([name, data]) => ({
                name,
                total: data.reduce((sum, n) => sum + n, 0),
                data,
            }))
            .sort((a, b) => {
                if (b.total !== a.total) return b.total - a.total;
                return a.name.localeCompare(b.name);
            });
        const signatureCounts = new Map();
        return rankedBarangays.map((entry, idx) => {
            const signature = JSON.stringify(entry.data);
            const overlapIndex = signatureCounts.get(signature) || 0;
            signatureCounts.set(signature, overlapIndex + 1);
            const seriesColor = analyticsSeriesColor(idx);
            const actualData = entry.data.slice();
            const visualData = actualData.map((value) => {
                if (value <= 0 || overlapIndex === 0) return value;
                return Number((value + overlapIndex * 0.08).toFixed(2));
            });
            return {
                label: entry.name,
                data: visualData,
                actualData,
                borderColor: seriesColor,
            };
        });
    };

    const renderRescueTrendChart = () => {
        const mode = rescueTrendViewFilter.value;
        const selectedYear = Number(rescueTrendYearFilter.value);
        const selectedMonth = Number(rescueTrendMonthFilter.value);
        rescueTrendMonthFilter.style.display = mode === "month" ? "inline-flex" : "none";

        const datasets = buildRescueTrendSeries(mode, selectedYear, selectedMonth);
        const hasData = datasets.length > 0;
        rescueTrendEmptyState.hidden = hasData;
        if (!hasData) {
            safePurge(rescueTrendEl);
            return;
        }

        const traces = datasets.map((ds, idx) => {
            const xIdx = ds.data.map((_, i) => i);
            const zPlane = xIdx.map(() => idx * (isAnalyticsPhone() ? 0.22 : 0.28));
            return {
                type: "scatter3d",
                mode: "lines+markers",
                name: ds.label,
                x: xIdx,
                y: ds.data,
                z: zPlane,
                customdata: ds.actualData,
                hovertemplate: "%{fullData.name}: %{customdata}<extra></extra>",
                line: { color: ds.borderColor, width: isAnalyticsPhone() ? 3 : 4 },
                marker: {
                    size: isAnalyticsTinyPhone() ? 3 : isAnalyticsPhone() ? 3.5 : 4,
                    color: ds.borderColor,
                    line: { color: "#fff", width: 1 },
                },
            };
        });

        const scene = {
            xaxis: { ...sceneAxes(), title: mode === "year" ? "Month index" : "Day" },
            yaxis: { ...sceneAxes(), title: "Rescues" },
            zaxis: { ...sceneAxes(), title: "Series" },
            camera: { eye: { x: 1.42, y: 1.55, z: 0.92 } },
        };
        mountPlot(rescueTrendEl, traces, layout3dLegend(scene, { y: 0.9 }));
    };

    /* ---------- Vaccination by barangay ---------- */
    const vaccinationBarangayData = D.vaccinationBarangay || {};
    const vaccinationYearFilter = document.getElementById("vaccinationBarangayYearFilter");
    const vaccinationViewFilter = document.getElementById("vaccinationBarangayViewFilter");
    const vaccinationMonthFilter = document.getElementById("vaccinationBarangayMonthFilter");
    const vaccinationDayFilter = document.getElementById("vaccinationBarangayDayFilter");
    const vaccinationEmptyState = document.getElementById("vaccinationBarangayEmptyState");
    const vaccinationEl = document.getElementById("vaccinationBarangayChart");
    const vaccinationEvents = vaccinationBarangayData.events || [];
    const vaccinationYears = (vaccinationBarangayData.years || []).slice().sort((a, b) => a - b);
    const vaccinationToday = new Date(`${vaccinationBarangayData.today}T00:00:00`);

    const parseIsoDate = (value) => {
        if (!value) return null;
        const parsed = new Date(`${value}T00:00:00`);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    };

    const resolveVaccinationDefaultYear = () => {
        const nowYear = new Date().getFullYear();
        if (vaccinationYears.includes(nowYear)) return nowYear;
        return vaccinationYears.length ? vaccinationYears[vaccinationYears.length - 1] : nowYear;
    };

    const resolveVaccinationDefaultDate = () => {
        const datePool = [];
        vaccinationEvents.forEach((event) => {
            if (event.vaccination_date) datePool.push(event.vaccination_date);
            if (event.vaccine_expiry_date) datePool.push(event.vaccine_expiry_date);
            if (event.dog_vaccination_expiry_date) datePool.push(event.dog_vaccination_expiry_date);
        });
        datePool.sort();
        if (datePool.length) return datePool[datePool.length - 1];
        return new Date().toISOString().slice(0, 10);
    };

    const selectedVaccinationYearDefault = resolveVaccinationDefaultYear();
    if (!vaccinationYears.length) {
        vaccinationYears.push(selectedVaccinationYearDefault);
    }

    vaccinationYears.forEach((year) => {
        const option = document.createElement("option");
        option.value = String(year);
        option.textContent = String(year);
        vaccinationYearFilter.appendChild(option);
    });
    vaccinationYearFilter.value = String(selectedVaccinationYearDefault);
    vaccinationMonthFilter.value = String(currentMonth);
    vaccinationDayFilter.value = resolveVaccinationDefaultDate();

    const matchesDateFilter = (dateObj, mode, year, month, selectedDay) => {
        if (!dateObj) return false;
        if (mode === "year") return dateObj.getFullYear() === year;
        if (mode === "month") {
            return dateObj.getFullYear() === year && dateObj.getMonth() + 1 === month;
        }
        if (!selectedDay) return false;
        return (
            dateObj.getFullYear() === selectedDay.getFullYear() &&
            dateObj.getMonth() === selectedDay.getMonth() &&
            dateObj.getDate() === selectedDay.getDate()
        );
    };

    const buildVaccinationBarangaySeries = (mode, year, month, selectedDay) => {
        const vaccinatedByBarangay = new Map();
        const expiredByBarangay = new Map();
        vaccinationEvents.forEach((event) => {
            const barangay = (event.barangay || "").trim();
            if (!barangay || barangay.toLowerCase() === "unknown") return;
            const registrationKey = String(event.registration_id || `unknown-${barangay}`);
            const vaccinationDate = parseIsoDate(event.vaccination_date);
            if (matchesDateFilter(vaccinationDate, mode, year, month, selectedDay)) {
                if (!vaccinatedByBarangay.has(barangay)) {
                    vaccinatedByBarangay.set(barangay, new Set());
                }
                vaccinatedByBarangay.get(barangay).add(registrationKey);
            }
            const expiryCandidates = [parseIsoDate(event.vaccine_expiry_date), parseIsoDate(event.dog_vaccination_expiry_date)];
            const isExpiredInFilter = expiryCandidates.some(
                (expiryDate) =>
                    expiryDate &&
                    expiryDate < vaccinationToday &&
                    matchesDateFilter(expiryDate, mode, year, month, selectedDay),
            );
            if (isExpiredInFilter) {
                if (!expiredByBarangay.has(barangay)) {
                    expiredByBarangay.set(barangay, new Set());
                }
                expiredByBarangay.get(barangay).add(registrationKey);
            }
        });
        const barangays = Array.from(new Set([...vaccinatedByBarangay.keys(), ...expiredByBarangay.keys()])).sort((a, b) => {
            const totalA = (vaccinatedByBarangay.get(a)?.size || 0) + (expiredByBarangay.get(a)?.size || 0);
            const totalB = (vaccinatedByBarangay.get(b)?.size || 0) + (expiredByBarangay.get(b)?.size || 0);
            if (totalA !== totalB) return totalB - totalA;
            return a.localeCompare(b);
        });
        return {
            labels: barangays,
            vaccinated: barangays.map((name) => vaccinatedByBarangay.get(name)?.size || 0),
            expired: barangays.map((name) => expiredByBarangay.get(name)?.size || 0),
        };
    };

    const renderVaccinationBarangayChart = () => {
        const mode = vaccinationViewFilter.value;
        const selectedYear = Number(vaccinationYearFilter.value);
        const selectedMonth = Number(vaccinationMonthFilter.value);
        const selectedDay = parseIsoDate(vaccinationDayFilter.value);
        vaccinationYearFilter.style.display = mode === "day" ? "none" : "inline-flex";
        vaccinationMonthFilter.style.display = mode === "month" ? "inline-flex" : "none";
        vaccinationDayFilter.style.display = mode === "day" ? "inline-flex" : "none";

        const { labels, vaccinated, expired } = buildVaccinationBarangaySeries(
            mode,
            selectedYear,
            selectedMonth,
            selectedDay,
        );
        const hasData = labels.length > 0;
        vaccinationEmptyState.hidden = hasData;
        if (!hasData) {
            safePurge(vaccinationEl);
            return;
        }

        const xi = labels.map((_, i) => i);
        const sizeVac = vaccinated.map((v) => (isAnalyticsTinyPhone() ? 5 : 6) + Math.min(v * 1.4, isAnalyticsPhone() ? 16 : 22));
        const sizeExp = expired.map((v) => (isAnalyticsTinyPhone() ? 5 : 6) + Math.min(v * 1.4, isAnalyticsPhone() ? 16 : 22));

        const traces = [
            {
                type: "scatter3d",
                mode: "markers",
                name: "Total Vaccinated",
                x: xi,
                y: vaccinated,
                z: xi.map(() => 0),
                customdata: labels,
                hovertemplate: "<b>%{customdata}</b><br>Vaccinated: %{y}<extra></extra>",
                marker: {
                    size: sizeVac,
                    color: "#2563eb",
                    opacity: 0.9,
                    line: { color: "#fff", width: 1 },
                    sizemode: "diameter",
                },
            },
            {
                type: "scatter3d",
                mode: "markers",
                name: "Expired Vaccination",
                x: xi,
                y: expired,
                z: xi.map(() => (isAnalyticsPhone() ? 0.55 : 0.75)),
                customdata: labels,
                hovertemplate: "<b>%{customdata}</b><br>Expired: %{y}<extra></extra>",
                marker: {
                    size: sizeExp,
                    color: "#dc2626",
                    opacity: 0.9,
                    line: { color: "#fff", width: 1 },
                    sizemode: "diameter",
                },
            },
        ];

        const scene = {
            xaxis: { ...sceneAxes(), title: "Barangay (index)" },
            yaxis: { ...sceneAxes(), title: "Unique registrations" },
            zaxis: { ...sceneAxes(), title: "", showticklabels: false },
            camera: { eye: { x: 1.38, y: 1.48, z: 0.95 } },
        };
        mountPlot(vaccinationEl, traces, layout3dLegend(scene));
    };

    /* ---------- Registered barangay pie ---------- */
    const barangayData = D.barangay || {};
    const registeredBarangayYearFilter = document.getElementById("registeredBarangayYearFilter");
    const registeredBarangayViewFilter = document.getElementById("registeredBarangayViewFilter");
    const registeredBarangayMonthFilter = document.getElementById("registeredBarangayMonthFilter");
    const registeredBarangayEmptyState = document.getElementById("registeredBarangayEmptyState");
    const registeredBarangayEl = document.getElementById("barangayChart");
    const registeredBarangayEvents = barangayData.events || [];
    const registeredBarangayYears = (barangayData.years || []).slice().sort((a, b) => a - b);

    const resolveRegisteredBarangayDefaultYear = () => {
        const nowYear = new Date().getFullYear();
        if (registeredBarangayYears.includes(nowYear)) return nowYear;
        return registeredBarangayYears.length ? registeredBarangayYears[registeredBarangayYears.length - 1] : nowYear;
    };

    const selectedRegisteredBarangayYearDefault = resolveRegisteredBarangayDefaultYear();
    if (!registeredBarangayYears.length) {
        registeredBarangayYears.push(selectedRegisteredBarangayYearDefault);
    }

    registeredBarangayYears.forEach((year) => {
        const option = document.createElement("option");
        option.value = String(year);
        option.textContent = String(year);
        registeredBarangayYearFilter.appendChild(option);
    });
    registeredBarangayYearFilter.value = String(selectedRegisteredBarangayYearDefault);
    registeredBarangayMonthFilter.value = String(currentMonth);

    const buildRegisteredBarangayPieData = (mode, year, month) => {
        const totalsByBarangay = new Map();
        registeredBarangayEvents.forEach((event) => {
            const eventDate = new Date(`${event.date}T00:00:00`);
            if (Number.isNaN(eventDate.getTime())) return;
            if (eventDate.getFullYear() !== year) return;
            if (mode === "month" && eventDate.getMonth() + 1 !== month) return;
            const barangay = event.barangay || "Unknown";
            totalsByBarangay.set(barangay, (totalsByBarangay.get(barangay) || 0) + 1);
        });
        const rankedBarangays = Array.from(totalsByBarangay.entries())
            .map(([label, total]) => ({ label, total }))
            .sort((a, b) => b.total - a.total);
        const topBarangays = rankedBarangays.slice(0, 6);
        const otherTotal = rankedBarangays.slice(6).reduce((sum, entry) => sum + entry.total, 0);
        const labels = topBarangays.map((entry) => entry.label);
        const values = topBarangays.map((entry) => entry.total);
        if (otherTotal > 0) {
            labels.push("Other Barangays");
            values.push(otherTotal);
        }
        const colors = labels.map((_, idx) => piePalette[idx % piePalette.length]);
        return { labels, values, colors };
    };

    const renderRegisteredBarangayChart = () => {
        const mode = registeredBarangayViewFilter.value;
        const selectedYear = Number(registeredBarangayYearFilter.value);
        const selectedMonth = Number(registeredBarangayMonthFilter.value);
        registeredBarangayMonthFilter.style.display = mode === "month" ? "inline-flex" : "none";

        const pie = buildRegisteredBarangayPieData(mode, selectedYear, selectedMonth);
        const hasData = pie.labels.length > 0;
        registeredBarangayEmptyState.hidden = hasData;
        if (!hasData) {
            safePurge(registeredBarangayEl);
            return;
        }

        const traces = buildPillarRingTraces(pie.labels, pie.values, pie.colors);
        mountPlot(registeredBarangayEl, traces, layout3d({ camera: { eye: { x: 1.52, y: 1.48, z: 1.18 } }, aspectmode: "cube" }));
    };

    function init() {
        if (typeof Plotly === "undefined") return;

        registerAnalyticsPlotElement(vaccinationBreedEl);
        registerAnalyticsPlotElement(adoptionClaimTrendEl);
        registerAnalyticsPlotElement(rescueTrendEl);
        registerAnalyticsPlotElement(vaccinationEl);
        registerAnalyticsPlotElement(registeredBarangayEl);

        vaccinationBreedYearFilter.addEventListener("change", renderVaccinationBreedChart);
        vaccinationBreedViewFilter.addEventListener("change", renderVaccinationBreedChart);
        vaccinationBreedMonthFilter.addEventListener("change", renderVaccinationBreedChart);
        vaccinationBreedTypeFilter.addEventListener("change", renderVaccinationBreedChart);

        adoptionClaimTrendYearFilter.addEventListener("change", renderAdoptionClaimTrendChart);
        adoptionClaimTrendViewFilter.addEventListener("change", renderAdoptionClaimTrendChart);
        adoptionClaimTrendMonthFilter.addEventListener("change", renderAdoptionClaimTrendChart);

        rescueTrendYearFilter.addEventListener("change", renderRescueTrendChart);
        rescueTrendViewFilter.addEventListener("change", renderRescueTrendChart);
        rescueTrendMonthFilter.addEventListener("change", renderRescueTrendChart);

        vaccinationYearFilter.addEventListener("change", renderVaccinationBarangayChart);
        vaccinationViewFilter.addEventListener("change", renderVaccinationBarangayChart);
        vaccinationMonthFilter.addEventListener("change", renderVaccinationBarangayChart);
        vaccinationDayFilter.addEventListener("change", renderVaccinationBarangayChart);

        registeredBarangayYearFilter.addEventListener("change", renderRegisteredBarangayChart);
        registeredBarangayViewFilter.addEventListener("change", renderRegisteredBarangayChart);
        registeredBarangayMonthFilter.addEventListener("change", renderRegisteredBarangayChart);

        renderVaccinationBreedChart();
        renderAdoptionClaimTrendChart();
        renderRescueTrendChart();
        renderVaccinationBarangayChart();
        renderRegisteredBarangayChart();

        registerAnalyticsRenderer(renderVaccinationBreedChart);
        registerAnalyticsRenderer(renderAdoptionClaimTrendChart);
        registerAnalyticsRenderer(renderRescueTrendChart);
        registerAnalyticsRenderer(renderVaccinationBarangayChart);
        registerAnalyticsRenderer(renderRegisteredBarangayChart);

        analyticsPhoneMediaQuery.addEventListener("change", scheduleAnalyticsRefresh);
        analyticsTinyPhoneMediaQuery.addEventListener("change", scheduleAnalyticsRefresh);
        window.addEventListener("resize", scheduleAnalyticsRefresh, { passive: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
