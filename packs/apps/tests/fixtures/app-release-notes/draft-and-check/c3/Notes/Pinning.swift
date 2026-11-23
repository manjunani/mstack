struct Pinning {
    var pinned: Set<String> = []
    mutating func toggle(_ id: String) {
        if pinned.contains(id) { pinned.remove(id) } else { pinned.insert(id) }
    }
}
