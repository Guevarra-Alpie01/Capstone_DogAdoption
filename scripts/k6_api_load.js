import http from "k6/http";
import { check, sleep } from "k6";


const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000";
const SCENARIO = (__ENV.SCENARIO || "steady").toLowerCase();
const COOKIE_HEADER = __ENV.COOKIE_HEADER || "";

const PUBLIC_PATHS = [
    { path: "/health/live/", weight: 1 },
    { path: "/health/ready/", weight: 1 },
    { path: "/user/", weight: 6 },
    { path: "/user/search/?q=dog", weight: 3 },
];

const AUTH_PATHS = [
    { path: "/user/announcements/", weight: 4 },
    { path: "/user/notifications/summary/", weight: 2 },
    { path: "/user/adopt-list/?filter=all", weight: 3 },
    { path: "/vetadmin/admin/announcements/", weight: 1 },
    { path: "/vetadmin/analytics/dashboard/", weight: 1 },
];

function buildOptions() {
    if (SCENARIO === "smoke") {
        return {
            vus: 10,
            duration: "1m",
            thresholds: {
                http_req_failed: ["rate<0.01"],
                http_req_duration: ["p(95)<600"],
            },
        };
    }

    if (SCENARIO === "stress") {
        return {
            scenarios: {
                stress: {
                    executor: "ramping-vus",
                    startVUs: 20,
                    stages: [
                        { duration: "2m", target: 100 },
                        { duration: "3m", target: 250 },
                        { duration: "3m", target: 400 },
                        { duration: "2m", target: 0 },
                    ],
                },
            },
            thresholds: {
                http_req_failed: ["rate<0.03"],
                http_req_duration: ["p(95)<1500"],
            },
        };
    }

    if (SCENARIO === "spike") {
        return {
            scenarios: {
                spike: {
                    executor: "ramping-vus",
                    startVUs: 0,
                    stages: [
                        { duration: "30s", target: 50 },
                        { duration: "30s", target: 500 },
                        { duration: "2m", target: 500 },
                        { duration: "1m", target: 50 },
                        { duration: "30s", target: 0 },
                    ],
                },
            },
            thresholds: {
                http_req_failed: ["rate<0.05"],
                http_req_duration: ["p(95)<2000"],
            },
        };
    }

    return {
        scenarios: {
            steady: {
                executor: "ramping-vus",
                startVUs: 20,
                stages: [
                    { duration: "2m", target: 100 },
                    { duration: "5m", target: 100 },
                    { duration: "1m", target: 0 },
                ],
            },
        },
        thresholds: {
            http_req_failed: ["rate<0.02"],
            http_req_duration: ["p(95)<1000"],
        },
    };
}

export const options = buildOptions();

function weightedPick(rows) {
    const totalWeight = rows.reduce((sum, row) => sum + row.weight, 0);
    let cursor = Math.random() * totalWeight;
    for (const row of rows) {
        cursor -= row.weight;
        if (cursor <= 0) {
            return row.path;
        }
    }
    return rows[rows.length - 1].path;
}

export default function () {
    const pool = COOKIE_HEADER ? PUBLIC_PATHS.concat(AUTH_PATHS) : PUBLIC_PATHS;
    const path = weightedPick(pool);
    const response = http.get(`${BASE_URL}${path}`, {
        headers: COOKIE_HEADER ? { Cookie: COOKIE_HEADER } : {},
        tags: {
            scenario_name: SCENARIO,
            endpoint: path,
        },
    });

    check(response, {
        "status is acceptable": (res) => res.status >= 200 && res.status < 400,
        "request id header exists": (res) => Boolean(res.headers["X-Request-ID"]),
    });

    sleep(0.5);
}
