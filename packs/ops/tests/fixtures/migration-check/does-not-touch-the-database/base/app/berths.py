def free_berths(cursor, min_length):
    cursor.execute("SELECT id, pier FROM berths WHERE length_m >= %s", (min_length,))
    return cursor.fetchall()
