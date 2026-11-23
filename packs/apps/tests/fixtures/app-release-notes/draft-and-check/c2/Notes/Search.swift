func matches(_ note: String, _ query: String) -> Bool {
    note.localizedCaseInsensitiveContains(query)
}
