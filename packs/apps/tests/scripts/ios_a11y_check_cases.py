"""Test ios-a11y-check's script on SwiftUI files and screenshots this test writes.

Usage: python3 ios_a11y_check_cases.py <new folder under .testrun/>

The Swift files are not compiled. No simulator, no VoiceOver.
"""
import sys

import fixtures as fx

W = fx.workdir(sys.argv)
SCRIPT = fx.SKILLS / "ios-a11y-check" / "scripts" / "a11ycheck.py"
PY = sys.executable
c = fx.Cases("ios-a11y-check")
GOOD = '''import SwiftUI
struct Row: View {
    var done: Bool
    var body: some View {
        HStack {
            Button {
                toggle()
            } label: {
                Image(systemName: "trash")
            }
            .accessibilityLabel("Delete note")
            Image(decorative: "stripe")
            Text("Title").font(.headline)
            Text("Body").font(.custom("Avenir", size: 15, relativeTo: .body))
            Image(systemName: done ? "checkmark.circle" : "circle")
                .foregroundColor(done ? .green : .gray)
                .accessibilityLabel(done ? "Done" : "Not done")
            Button("Save") { save() }
        }
    }
}
'''
BAD = '''import SwiftUI
struct Bar: View {
    var online: Bool
    var body: some View {
        VStack {
            Button(action: share) {
                Image(systemName: "square.and.arrow.up")
            }
            Image("hero")
            Text("Price").font(.system(size: 13))
            Text("Small").font(.custom("Avenir", size: 11))
            Circle()
                .fill(online ? .green : .red)
                .frame(width: 8, height: 8)
        }
    }
}
'''
(W / "good").mkdir()
(W / "good" / "Row.swift").write_text(GOOD)
(W / "bad").mkdir()
(W / "bad" / "Bar.swift").write_text(BAD)
run = lambda want, label, args: c.run(want, label, [PY, SCRIPT] + [str(a) for a in args])
run(0, "scan: labelled, decorative and relative fonts pass", ["scan", W / "good"])
c.has("0 warnings")
c.has("not verified by a source scan: VoiceOver reading order")
run(1, "scan: icon button, two fixed fonts fail", ["scan", W / "bad"])
c.has("icon button     Bar.swift:7")
c.has("fixed font      Bar.swift:10")
c.has("fixed font      Bar.swift:11")
c.has("image no label  Bar.swift:9")
c.has("colour only     Bar.swift:13")
c.has("3 failures, 2 warnings")
(W / "empty").mkdir()
run(2, "scan: no Swift files is blocked", ["scan", W / "empty"])
run(2, "scan: missing folder is blocked", ["scan", W / "nope"])
shots = W / "shots"
fx.write_png(shots / "home-AX5.png", fx.picture(390, 844, seed=1))
fx.write_png(shots / "settings-AX5.png", fx.picture(390, 844, seed=2))
run(0, "shots: real pictures with every expected screen", ["shots", shots, "--expect", "home", "settings"])
c.has("whether the text size really was the largest")
run(1, "shots: an expected screen without a file fails", ["shots", shots, "--expect", "home", "editor"])
c.has("no screenshot for 'editor'")
fx.write_png(shots / "editor-AX5.png", fx.flat(390, 844))
run(1, "shots: a blank screenshot fails", ["shots", shots, "--expect", "editor"])
run(2, "shots: empty folder is blocked", ["shots", W / "empty"])
c.run(0, "--help works", [PY, SCRIPT, "--help"])
sys.exit(c.finish())
