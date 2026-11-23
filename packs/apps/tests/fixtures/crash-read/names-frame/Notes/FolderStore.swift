import Foundation

final class FolderStore {
    private(set) var folders: [String] = ["Inbox", "Work", "Home"]

    func remove(at index: Int) {
        folders.remove(at: index)
    }


















































    // The sidebar keeps the index it was given before a folder was removed.
    func folder(at index: Int) -> String {
        return folders[index]
    }
}
