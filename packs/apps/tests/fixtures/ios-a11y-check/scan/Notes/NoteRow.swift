import SwiftUI

struct NoteRow: View {
    let note: Note
    var onPin: () -> Void

    var body: some View {
        HStack {
            Image(systemName: note.isPinned ? "pin.fill" : "pin")
                .foregroundColor(note.isPinned ? .orange : .gray)
            VStack(alignment: .leading) {
                Text(note.title).font(.headline)
                Text(note.preview).font(.system(size: 12))
            }
            Spacer()
            Button(action: onPin) {
                Image(systemName: "pin.circle")
            }
        }
    }
}
