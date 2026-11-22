"""Script test for export-check: plan without running, real encodes checked against presets, and files that break a limit.

Usage: export_check_cases.py <new folder>   (for example .testrun/media-export-check)
"""
import argparse
import hashlib
import json

import fixtures as fx

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
root = fx.new_folder(parser.parse_args().folder)
E = fx.script("export-check", "export_check.py")
c = fx.Cases("export-check cases")

wide = fx.video(root / "wide.mp4", 8, quiet=[(3, 4)])                      # 640x360, 25 fps, tone with one pause
fast = fx.video(root / "fast.mp4", 6, fps=50)                              # 50 fps, for the frame-rate cap
silent_film = fx.video(root / "silent-film.mp4", 4, audio=False)
talk = fx.tone(root / "talk.wav", 12, quiet=[(4, 5), (9, 10)])
before = hashlib.sha256(wide.read_bytes()).hexdigest()
# A file at the right size that breaks four other limits: pixel format, sample rate, loudness, true peak.
# ffmpeg's sine source peaks near -18 dBFS, so +17.7 dB lifts it to about -0.3 dBFS.
fx.ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=4", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100:duration=4",
          "-af", "volume=17.7dB", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv444p", "-c:a", "aac", root / "wrong.mp4")
(root / "empty.mp4").write_bytes(b"")

out = c.case("presets: list", [E, "presets"], 0, must_print="UNVERIFIED")
# Some preset numbers were checked against their sources on 2026-11-22; the list must label each one.
c.expect("every preset number is labelled verified or UNVERIFIED",
         all(line.rstrip().endswith(("verified", "UNVERIFIED")) for line in out.splitlines() if "checked 20" in line))
c.case("plan: no --run prints the command and encodes nothing", [E, "plan", wide, "--preset", "youtube-1080p", "--out", root / "o" / "wide-yt.mp4"], 2, must_print="plan only")
c.expect("no output file exists after a plan", not (root / "o").exists())
out = c.case("plan --run: landscape source to youtube-1080p", [E, "plan", wide, "--preset", "youtube-1080p", "--out", root / "o" / "wide-yt.mp4", "--run"], 0)
c.expect("the report says the preset numbers are unverified", "UNVERIFIED" in out)
c.case("check: that export again, with its source", [E, "check", root / "o" / "wide-yt.mp4", "--preset", "youtube-1080p", "--source", wide], 0)
c.case("check: the same export against a vertical preset", [E, "check", root / "o" / "wide-yt.mp4", "--preset", "youtube-short"], 1, must_print="resolution")
out = c.case("plan --run: landscape source to a vertical preset (bars, with a warning)", [E, "plan", wide, "--preset", "youtube-short", "--out", root / "o" / "wide-short.mp4", "--run"], 0, must_print="bars will be added")
c.case("plan --run: 50 fps source to a 30 fps preset", [E, "plan", fast, "--preset", "instagram-reel", "--out", root / "o" / "fast-reel.mp4", "--run"], 0, must_print="at most 30")
out = c.case("check: raw source against youtube-1080p", [E, "check", wide, "--preset", "youtube-1080p"], 1)
c.expect("resolution and loudness are both reported as FAIL", out.count("FAIL") >= 2 and "640x360" in out)
out = c.case("check: right size, wrong pixel format, sample rate and level", [E, "check", root / "wrong.mp4", "--preset", "youtube-1080p"], 1)
for label in ("pixel format", "sample rate", "integrated loudness", "true peak"):
    c.expect(f"'{label}' is marked FAIL", any(label in line and "FAIL" in line for line in out.splitlines()))
c.case("plan --run: picture with no sound cannot be fully measured", [E, "plan", silent_film, "--preset", "youtube-1080p", "--out", root / "o" / "silent.mp4", "--run"], 2, must_print="not verified")
c.case("plan --run: speech to podcast-mp3", [E, "plan", talk, "--preset", "podcast-mp3", "--out", root / "o" / "talk.mp3", "--run"], 0)
c.case("check: the .wav itself against podcast-mp3", [E, "check", talk, "--preset", "podcast-mp3"], 1, must_print="audio codec")
c.case("check: a video against the audio preset", [E, "check", wide, "--preset", "podcast-mp3"], 1, must_print="none (audio preset)")

# A presets file of the user's own: a 3 second, 10 kilobyte limit that the 8 second export breaks.
own = json.loads((fx.PACK / "skills" / "export-check" / "references" / "presets.json").read_text())
tiny = own["presets"]["youtube-1080p"]
tiny["limits"]["max_duration"]["value"], tiny["limits"]["max_size_mb"]["value"] = 3, 0.01
tiny["limits"]["min_duration"] = dict(tiny["limits"]["max_duration"], value=1)
own["presets"] = {"tiny": tiny}
(root / "own.json").write_text(json.dumps(own))
out = c.case("check: user's own presets file, duration and size limits", [E, "--presets", root / "own.json", "check", root / "o" / "wide-yt.mp4", "--preset", "tiny"], 1)
c.expect("duration and file size are both FAIL", sum(1 for l in out.splitlines() if ("duration" in l or "file size" in l) and "FAIL" in l) == 2)

c.case("plan: unknown preset", [E, "plan", wide, "--preset", "myspace", "--out", root / "o" / "x.mp4"], 2, must_print="no preset named")
c.case("plan: output already exists", [E, "plan", wide, "--preset", "youtube-1080p", "--out", root / "o" / "wide-yt.mp4", "--run"], 2, must_print="already exists")
c.case("plan: output is the source", [E, "plan", wide, "--preset", "youtube-1080p", "--out", wide, "--run"], 2, must_print="blocked")
c.case("plan: wrong file extension for the preset", [E, "plan", wide, "--preset", "youtube-1080p", "--out", root / "o" / "x.mov"], 2, must_print="writes .mp4")
c.case("plan: audio file to a video preset", [E, "plan", talk, "--preset", "tiktok", "--out", root / "o" / "t.mp4"], 2, must_print="no picture")
c.case("check: empty file", [E, "check", root / "empty.mp4", "--preset", "youtube-1080p"], 1, must_print="cannot be read")
c.case("check: missing file", [E, "check", root / "none.mp4", "--preset", "youtube-1080p"], 2, must_print="blocked")
c.case("check: presets file missing", [E, "--presets", root / "none.json", "check", wide, "--preset", "tiny"], 2, must_print="blocked")
c.expect("the source is byte-for-byte unchanged", hashlib.sha256(wide.read_bytes()).hexdigest() == before)
raise SystemExit(c.finish())
