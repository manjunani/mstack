import SwiftUI

struct NoteList: View {
    var notes: [String]
    var body: some View {
        List(notes, id: \.self) { Text($0) }
    }
}
