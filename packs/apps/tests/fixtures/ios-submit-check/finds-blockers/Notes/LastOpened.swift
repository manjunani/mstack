import Foundation

/// Remembers which note was open, so the app reopens it on the next launch.
enum LastOpened {
    static func save(_ id: String) {
        UserDefaults.standard.set(id, forKey: "lastOpenedNote")
    }

    static func load() -> String? {
        UserDefaults.standard.string(forKey: "lastOpenedNote")
    }
}
