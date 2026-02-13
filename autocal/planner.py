# This file is for plan_actions + note diff logic


def format_note(old_note, new_note, separator=" | "):
    old_note = "" if old_note is None else str(old_note)
    parts = [p.strip() for p in old_note.split(separator) if p.strip()]
    kept = [p for p in parts if not p.startswith("AUTOHOL:")]
    kept.append(new_note)
    return separator.join(kept)[:200]


def build_note(hdate):
    return f"AUTOHOL: Holiday, {hdate:%m/%d/%Y}"


def plan_actions(records, country, hdate, note_text):
    actions = []
    for rec in records:
        old = (rec.fdNotes or "")
        new = format_note(old, note_text)[:200]

        if new == old:
            action_type = "SKIP_NO_CHANGE"
        else:
            action_type = "UPDATE_NOTE"

        actions.append({
            "country": country,
            "holiday_date": hdate.strftime("%Y-%m-%d"),
            "fdRecID": rec.fdRecID,
            "database": getattr(rec, "fdDatabaseName", ""),
            "group": getattr(rec, "fdGroup", ""),
            "update": getattr(rec, "fdMessageBoard", ""),
            "action_type": action_type,
            "old_note": old[:200],
            "new_note": new[:200],
            "result": "PLANNED", 
        })
    return actions