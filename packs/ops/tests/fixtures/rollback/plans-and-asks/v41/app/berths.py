def list_berths(cursor):
    cursor.execute("SELECT id, pier, length_m FROM berths ORDER BY pier")
    return cursor.fetchall()
