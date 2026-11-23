def greeting(cursor, user_id):
    cursor.execute("SELECT fullname FROM users WHERE id = %s", (user_id,))
    (name,) = cursor.fetchone()
    return f"Welcome back, {name}"
