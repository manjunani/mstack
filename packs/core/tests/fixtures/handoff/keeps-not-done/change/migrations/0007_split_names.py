"""Split members.full_name into given_name and family_name."""


def upgrade(conn):
    conn.execute("ALTER TABLE members ADD COLUMN given_name TEXT")
    conn.execute("ALTER TABLE members ADD COLUMN family_name TEXT")
    for member_id, full in conn.execute("SELECT id, full_name FROM members").fetchall():
        given, _, family = full.partition(" ")
        conn.execute("UPDATE members SET given_name = ?, family_name = ? WHERE id = ?", (given, family, member_id))


# downgrade() is still to be written
