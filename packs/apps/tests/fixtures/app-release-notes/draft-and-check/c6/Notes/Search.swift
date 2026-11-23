func matches(_ note: String, _ query: String) -> Bool {
    // Compare against a lower-cased copy made once, not per character.
    let needle = query.lowercased()
    return note.lowercased().contains(needle)
}
