def list_berths(cursor, pier=None):
    if pier:
        cursor.execute("SELECT id, pier, length_m, depth_m FROM berths WHERE pier = %s", (pier,))
    else:
        cursor.execute("SELECT id, pier, length_m, depth_m FROM berths ORDER BY pier")
    return cursor.fetchall()
