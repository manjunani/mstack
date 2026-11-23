def greeting(cursor, user_id):
    cursor.execute("SELECT display_name FROM users WHERE id = %s", (user_id,))
    (name,) = cursor.fetchone()
    return f"Welcome back, {name}"
