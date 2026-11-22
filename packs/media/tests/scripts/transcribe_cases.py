"""Script test for transcribe: audio extraction, the coverage validator, format conversion and every blocked path.

No speech recogniser is used. Transcripts are written by hand to match a tone with silent gaps.
The API case talks to a stand-in server started by this test on 127.0.0.1; nothing leaves the machine.
Usage: transcribe_cases.py <new folder>   (for example .testrun/media-transcribe)
"""
import argparse
import hashlib
import http.server
import json
import os
import pathlib
import shutil
import threading

import fixtures as fx

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("folder")
root = fx.new_folder(parser.parse_args().folder)
T = fx.script("transcribe", "transcribe.py")
c = fx.Cases("transcribe cases")

# Voiced 0.5-3.0 and 5.0-8.0; silent elsewhere. 10 seconds.
talk = fx.tone(root / "talk.wav", 10, quiet=[(0, 0.5), (3, 5), (8, 10)])
mute_video = fx.video(root / "mute.mp4", 2, audio=False)
before = hashlib.sha256(talk.read_bytes()).hexdigest()
first, second = fx.spread("this is the first part of the talk", 0.6, 2.9), fx.spread("and here comes the second part now", 5.1, 7.9)

good = fx.words_json(root / "good.json", first + second, 10)
half = fx.words_json(root / "half.json", first, 10)
ghost = fx.words_json(root / "ghost.json", fx.spread("thanks for watching please subscribe", 3.4, 4.6) + fx.spread("more words in silence", 8.5, 9.6), 10)
unscored = root / "unscored.json"
unscored.write_text(json.dumps({"words": [{"word": w, "start": s, "end": e} for w, s, e in first + second]}), encoding="utf-8")
shuffled = fx.words_json(root / "shuffled.json", second + first, 10)
doubtful = fx.words_json(root / "doubtful.json", [(w, s, e, 0.31 if w in ("talk", "comes") else 0.95) for w, s, e in first + second], 10)
empty = fx.words_json(root / "empty.json", [], 10)
silence = fx.tone(root / "silence.wav", 4, quiet=[(0, 4)])

c.case("audio: extract mono 16 kHz", [T, "audio", talk, "--out-dir", root / "out"], 0)
c.case("audio: file with no audio stream", [T, "audio", mute_video, "--out-dir", root / "out"], 2, must_print="blocked")
c.case("check: transcript covers both voiced stretches", [T, "check", good, "--media", talk], 0)
c.case("check: second voiced stretch has no words", [T, "check", half, "--media", talk], 1, must_print="voiced, no words")
c.case("check: every word sits in silence", [T, "check", ghost, "--media", talk], 1, must_print="words placed in silence")
c.case("check: engine gave no confidence", [T, "check", unscored, "--media", talk], 2, must_print="not verified")
c.case("check: words out of time order", [T, "check", shuffled, "--media", talk], 1, must_print="before the previous word")
out = c.case("check: two low-confidence words are listed", [T, "check", doubtful, "--media", talk], 0, must_print="2 low-confidence words")
c.expect("the listed words are 'talk' and 'comes'", "talk  (0.31)" in out and "comes  (0.31)" in out)
c.case("check: empty transcript, voiced recording", [T, "check", empty, "--media", talk], 1)
c.case("check: empty transcript, silent recording", [T, "check", empty, "--media", silence], 0, must_print="nothing spoken")
c.case("check: transcript file is not JSON", [T, "check", talk, "--media", talk], 2, must_print="blocked")

# Conversion from the two recogniser shapes this script knows (samples written by hand in those shapes).
whisper = root / "whisper.json"
whisper.write_text(json.dumps({"text": "x", "segments": [{"words": [
    {"word": " " + w, "start": s, "end": e, "probability": 0.88} for w, s, e in first + second]}]}), encoding="utf-8")
cpp = root / "cpp.json"
cpp.write_text(json.dumps({"transcription": [{"tokens": [
    {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}, "p": 0.9},
    {"text": " tran", "offsets": {"from": 600, "to": 900}, "p": 0.95}, {"text": "script", "offsets": {"from": 900, "to": 1400}, "p": 0.55},
    {"text": " ready", "offsets": {"from": 1500, "to": 2800}, "p": 0.9}, {"text": " again", "offsets": {"from": 5100, "to": 7900}, "p": 0.9}]}]}), encoding="utf-8")
c.case("import: openai-whisper shape", [T, "import", whisper, "--media", talk, "--out-dir", root / "imp"], 0)
c.case("check: the imported transcript", [T, "check", root / "imp" / "talk.transcript.json", "--media", talk], 0)
c.case("import: whisper.cpp shape, no recording given", [T, "import", cpp, "--out-dir", root / "imp2"], 2, must_print="not verified")
merged = json.loads((root / "imp2" / "cpp.transcript.json").read_text())["words"]
c.expect("word pieces are joined and keep the lowest confidence", [w["word"] for w in merged] == ["transcript", "ready", "again"] and merged[0]["confidence"] == 0.55,
         str([(w["word"], w["confidence"]) for w in merged]))
c.case("import: file does not exist", [T, "import", empty.with_name("none.json")], 2, must_print="blocked")
(root / "plain.json").write_text(json.dumps({"segments": [{"text": "no word timings here"}]}), encoding="utf-8")
c.case("import: segments without word timestamps", [T, "import", root / "plain.json", "--out-dir", root / "imp3"], 1, must_print="word timestamps")

# find: nothing yet, then a transcript beside the recording.
c.case("find: nothing exists yet", [T, "find", talk], 2, cwd=root)
shutil.copy(root / "imp" / "talk.transcript.json", root / "talk.transcript.json")
c.case("find: transcript beside the recording", [T, "find", talk], 0, cwd=root)

# Blocked paths. A folder that holds only ffmpeg and ffprobe stands in for a machine with no recogniser.
tools = root / "bin"
tools.mkdir()
for name in ("ffmpeg", "ffprobe"):
    os.symlink(shutil.which(name), tools / name)
bare = {**os.environ, "PATH": str(tools)}
c.case("run: no recogniser on the path", [T, "run", talk, "--out-dir", root / "run"], 2, env=bare, must_print="blocked: no speech recogniser")
c.case("run: ffmpeg missing", [T, "audio", talk], 2, env={**os.environ, "PATH": str(root / "nowhere")}, must_print="blocked: ffmpeg")
c.case("run: API named, no yes from the user", [T, "run", talk, "--api-url", "http://127.0.0.1:9/v1", "--api-key-env", "MSTACK_TEST_KEY",
                                                 "--out-dir", root / "run"], 2, env=bare, must_print="blocked: uploading needs")
c.expect("nothing was extracted or sent before the yes", not (root / "run" / "talk.16k.wav").exists())


class Stand(http.server.BaseHTTPRequestHandler):
    seen = {}

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Stand.seen = {"auth": self.headers.get("Authorization"), "has_wav": b"RIFF" in body, "word": b"timestamp_granularities" in body}
        reply = json.dumps({"text": "x", "words": [{"word": w, "start": s, "end": e} for w, s, e in first + second]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Stand)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}/v1/transcribe"
c.case("run: API with the yes, key variable empty", [T, "run", talk, "--api-url", url, "--api-key-env", "MSTACK_TEST_KEY", "--allow-upload",
                                                      "--out-dir", root / "api"], 2, env=bare, must_print="blocked: the environment variable")
c.expect("no audio was extracted while the key was missing", not (root / "api").exists() or not any((root / "api").iterdir()))
c.case("run: API with the yes (stand-in server, no confidence in the reply)",
       [T, "run", talk, "--api-url", url, "--api-key-env", "MSTACK_TEST_KEY", "--allow-upload", "--out-dir", root / "api"], 2,
       env={**bare, "MSTACK_TEST_KEY": "test-value"}, must_print="coverage passed")
c.expect("the stand-in server got the audio, the key header and the word-timing request",
         Stand.seen == {"auth": "Bearer test-value", "has_wav": True, "word": True}, str(Stand.seen))
c.expect("the API transcript was written", (root / "api" / "talk.transcript.json").exists())
server.shutdown()

c.expect("the source recording is byte-for-byte unchanged", hashlib.sha256(talk.read_bytes()).hexdigest() == before)
raise SystemExit(c.finish())
