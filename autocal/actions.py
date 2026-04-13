# This file is for apply/update functions (writes)

def apply_actions(conn, cursor, actions, dry_run):
    wrote = 0
    for a in actions:
        if a["action_type"] != "UPDATE_NOTE":
            a["result"] = "SKIP_NO_CHANGE"
            continue

        if dry_run:
            a["result"] = "DRY_RUN"
            continue

        try:
            cursor.execute(
                "UPDATE tblcalendar_dw_records SET fdNotes=? WHERE fdRecID=?;",
                (a["new_note"], a["fdRecID"])
            )
            a["result"] = "WROTE"
            wrote += 1
        except Exception as e:
            a["result"] = "ERROR"
            a["error"] = str(e)

    if not dry_run and wrote > 0:
        conn.commit()

    return wrote