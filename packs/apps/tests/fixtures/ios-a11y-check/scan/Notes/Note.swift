import Foundation

struct Note: Identifiable {
    let id = UUID()
    var title: String
    var preview: String
    var isPinned = false
}
