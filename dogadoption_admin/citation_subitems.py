"""Catalog and helpers for citation penalty sub-lines (tiered / breakdown fees)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# code -> (parent_sec29_number, amount, print_label)
SUBITEM_CATALOG: dict[str, tuple[int, Decimal, str]] = {
    "s29_14_fine": (
        14,
        Decimal("5000.00"),
        "Fine — 4th recorded offense (forced neutering)",
    ),
    "s29_20_24h": (20, Decimal("500.00"), "Redemption fee — within 24 hrs"),
    "s29_20_48h": (20, Decimal("1000.00"), "Redemption fee — within 48 hrs"),
    "s29_20_72h": (20, Decimal("1500.00"), "Redemption fee — within 72 hrs"),
    "s29_24_ex1": (24, Decimal("500.00"), "Exceeding 4 heads — 1 excess"),
    "s29_24_ex2": (24, Decimal("1000.00"), "Exceeding 4 heads — 2 excess"),
}

# Section 29 penalty numbers: if any subitem is recorded for N, parent's amount is omitted from the fee total (subs replace that bucket).
SUBITEM_FEE_PARENT_NUMBERS = frozenset({14, 20, 24})


def merge_penalty_ids_with_subitem_parents(
    posted_penalty_ids: list,
    posted_sub_codes: list[str],
    section29_penalty_id_by_number: dict[int, int],
) -> tuple[set[int], set[int]]:
    """
    Union of posted penalty PKs and parents implied by posted subitem codes.
    Returns (merged_ids, missing_parent_numbers) when a sub references a parent not in the map.
    """
    merged: set[int] = set()
    for x in posted_penalty_ids:
        if str(x).isdigit():
            merged.add(int(x))
    missing: set[int] = set()
    for code in posted_sub_codes:
        spec = SUBITEM_CATALOG.get((code or "").strip())
        if not spec:
            continue
        parent_num = spec[0]
        pid = section29_penalty_id_by_number.get(parent_num)
        if pid is None:
            missing.add(parent_num)
            continue
        merged.add(pid)
    return merged, missing


def normalize_subitems(raw: Any) -> list[dict[str, str]]:
    if not raw:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if code not in SUBITEM_CATALOG:
            continue
        _, _, label = SUBITEM_CATALOG[code]
        amount = str(row.get("amount") or SUBITEM_CATALOG[code][1])
        out.append({"code": code, "label": label, "amount": amount})
    return out


def collect_subitems_from_post(
    posted_codes: list[str],
    selected_penalties: list,
) -> tuple[list[dict[str, str]], list[str]]:
    """
    Validate posted subitem codes against selected Sec. 29 parent penalties.
    Returns (stored_rows, error_messages).
    """
    sec29_numbers = {
        p.number
        for p in selected_penalties
        if getattr(getattr(p, "section", None), "number", None) == 29
    }
    rejected_parents: set[int] = set()
    seen: set[str] = set()
    stored: list[dict[str, str]] = []
    for code in posted_codes:
        code = (code or "").strip()
        if not code or code in seen:
            continue
        spec = SUBITEM_CATALOG.get(code)
        if not spec:
            continue
        parent_num, amount, label = spec
        if parent_num not in sec29_numbers:
            rejected_parents.add(parent_num)
            continue
        seen.add(code)
        stored.append({"code": code, "label": label, "amount": str(amount)})
    errors = [
        f"Select Section 29 violation no. {n} before adding its fee tier lines."
        for n in sorted(rejected_parents)
    ]
    return stored, errors


def citation_fee_total(selected_penalties: list, subitems: list[dict[str, str]]) -> Decimal:
    """
    Sum monetary amounts: parent penalties, minus parents that have sub-lines (replaced by sub amounts).
    """
    parents_with_subs: set[int] = set()
    for row in subitems:
        code = row.get("code") or ""
        spec = SUBITEM_CATALOG.get(code)
        if spec:
            parents_with_subs.add(spec[0])

    total = Decimal("0.00")
    for p in selected_penalties:
        sec_num = getattr(getattr(p, "section", None), "number", None)
        if sec_num == 29 and p.number in SUBITEM_FEE_PARENT_NUMBERS and p.number in parents_with_subs:
            continue
        total += p.amount

    for row in subitems:
        try:
            total += Decimal(str(row.get("amount", "0")))
        except Exception:
            continue

    return total
