import SwiftUI

struct SettingsView: View {
    @AppStorage("sortByDate") private var sortByDate = true

    var body: some View {
        Form {
            Image("settings-banner")
            Toggle("Sort by date", isOn: $sortByDate)
            Button {
                exportAll()
            } label: {
                Image(systemName: "square.and.arrow.up")
            }
            .accessibilityLabel("Export all notes")
            Text("Version 1.1").font(.custom("Avenir", size: 11, relativeTo: .footnote))
        }
    }

    private func exportAll() {}
}
