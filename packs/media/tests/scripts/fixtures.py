"""Helpers shared by the script tests of the media pack: make small test media with ffmpeg, run a case, keep score.

Nothing here is a recording of a person. "Speech" is a sine tone with silent gaps, which is enough for
silence detection, loudness and cut arithmetic. Python standard library only.
"""
import json
import pathlib
import subprocess
import sys

PACK = pathlib.Path(__file__).resolve().parents[2]


def script(skill, name):
    return str(PACK / "skills" / skill / "scripts" / name)


def new_folder(path):
    path = pathlib.Path(path).resolve()
    if path.exists():
        sys.exit(f"refusing: {path} already exists; give a new folder")
    path.mkdir(parents=True)
    return path


def ffmpeg(*args):
    done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit("fixture failed: " + done.stderr[-400:])


def tone(path, seconds, quiet=(), freq=220, volume_db=-12, rate=44100, extra=()):
    """A sine tone with silent gaps. quiet = [(start, end), ...]."""
    gate = "+".join(f"between(t,{a},{b})" for a, b in quiet)
    chain = f"volume={volume_db}dB" + (f",volume=0:enable='{gate}'" if gate else "")
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate={rate}:duration={seconds}", "-af", chain, *extra, path)
    return path


def video(path, seconds, quiet=(), size="640x360", fps=25, audio=True, extra=()):
    """A moving test picture with a tone that has silent gaps."""
    args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={seconds}"]
    if audio:
        gate = "+".join(f"between(t,{a},{b})" for a, b in quiet)
        chain = "volume=-12dB" + (f",volume=0:enable='{gate}'" if gate else "")
        args += ["-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={seconds}", "-af", chain, "-c:a", "aac", "-b:a", "128k"]
    ffmpeg(*args, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", *extra, path)
    return path


def words_json(path, words, duration, confidence=0.9):
    """words = [(text, start, end)] or [(text, start, end, confidence)]."""
    items = [{"word": w[0], "start": w[1], "end": w[2], "confidence": w[3] if len(w) > 3 else confidence} for w in words]
    pathlib.Path(path).write_text(json.dumps({"format": "mstack-transcript-1", "source": "", "duration": duration,
                                              "engine": "written by hand for a test", "words": items}, indent=1), encoding="utf-8")
    return path


def spread(text, start, end):
    """Give each word of a sentence an equal slice of the time between start and end."""
    parts = text.split()
    step = (end - start) / len(parts)
    return [(w, round(start + i * step, 3), round(start + (i + 0.8) * step, 3)) for i, w in enumerate(parts)]


class Cases:
    def __init__(self, title):
        self.title, self.run_count, self.wrong = title, 0, 0

    def case(self, name, command, want, cwd=None, must_print=None, env=None):
        """Run one command, compare its exit code with the expected one, and return its output."""
        done = subprocess.run([sys.executable, *map(str, command)], capture_output=True, text=True, cwd=cwd, env=env)
        output = done.stdout + done.stderr
        last = (done.stdout.strip().splitlines() or ["(no output)"])[-1]
        ok = done.returncode == want and (must_print is None or must_print in output)
        self.run_count += 1
        self.wrong += not ok
        print(f"{'ok  ' if ok else 'BAD '}{name}: exit {done.returncode} (expect {want})  |  {last[:150]}")
        if not ok:
            print("      " + "\n      ".join(output.strip().splitlines()[-12:]))
        return output

    def expect(self, name, condition, detail=""):
        self.run_count += 1
        self.wrong += not condition
        print(f"{'ok  ' if condition else 'BAD '}{name}{': ' + detail if detail else ''}")

    def finish(self):
        print(f"{self.title}: {self.run_count} run, {self.wrong} wrong")
        return 1 if self.wrong else 0
