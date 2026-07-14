"""Shared client-facing labels for non-federal tax-summary rows."""


def _normalize_display_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    label = value.strip()
    while label.endswith(":"):
        label = label[:-1].rstrip()
    return label or None


def _nonblank(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def resolve_tax_summary_labels(items: list[dict]) -> list[str]:
    """Return one display label per state/local tax-summary item.

    New Task 2 payloads provide ``display_label`` for local or regional
    jurisdictions and ``None`` for ordinary states.  Missing labels keep the
    historical single-state/multi-state rendering behavior for stored data.
    """
    explicit = [_normalize_display_label(item.get("display_label")) for item in items]
    ordinary_state_count = sum(label is None for label in explicit)
    labels: list[str] = []

    for item, display_label in zip(items, explicit):
        if display_label is not None:
            labels.append(display_label)
            continue
        if ordinary_state_count == 1:
            labels.append("State Income Tax")
            continue
        jurisdiction = (
            _nonblank(item.get("state_abbreviation"))
            or _nonblank(item.get("state_name"))
        )
        labels.append(
            f"{jurisdiction} State Income Tax" if jurisdiction else "State Income Tax"
        )
    return labels
