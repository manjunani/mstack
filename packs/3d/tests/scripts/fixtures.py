"""Build tiny model and image files for the script tests, with the standard library only.

Every file is written from code in this module, so a test never depends on a downloaded asset.
Import it and call the functions, or run it:  fixtures.py <new folder>
"""
import argparse
import json
import math
import pathlib
import struct
import sys
import zlib

CHUNK_JSON, CHUNK_BIN = 0x4E4F534A, 0x004E4942


def pad(data, fill):
    return data + fill * (-len(data) % 4)


def glb(doc, binary=b"", declared_length=None, json_length=None):
    """Pack a JSON document and a binary blob into a GLB. The optional arguments write wrong lengths on purpose."""
    text = pad(json.dumps(doc, separators=(",", ":")).encode("utf-8"), b" ")
    body = struct.pack("<II", len(text) if json_length is None else json_length, CHUNK_JSON) + text
    if binary:
        blob = pad(binary, b"\x00")
        body += struct.pack("<II", len(blob), CHUNK_BIN) + blob
    total = 12 + len(body)
    return struct.pack("<III", 0x46546C67, 2, total if declared_length is None else declared_length) + body


def png(width, height, pixel, colour=6, depth=8, interlace=0, filters=(0,)):
    """Encode a PNG. pixel(x, y) returns the channel values of one pixel. filters is cycled per row."""
    channels = {0: 1, 2: 3, 4: 2, 6: 4, 3: 1}[colour] * (depth // 8)
    rows, previous = [], bytes(width * channels)
    for y in range(height):
        line = bytes(v for x in range(width) for v in pixel(x, y))
        kind = filters[y % len(filters)]
        out = bytearray(len(line))
        for i, value in enumerate(line):
            a = line[i - channels] if i >= channels else 0
            b = previous[i]
            c = previous[i - channels] if i >= channels else 0
            if kind == 0:
                guess = 0
            elif kind == 1:
                guess = a
            elif kind == 2:
                guess = b
            elif kind == 3:
                guess = (a + b) >> 1
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                guess = a if pa <= pb and pa <= pc else b if pb <= pc else c
            out[i] = (value - guess) & 255
        rows.append(bytes([kind]) + bytes(out))
        previous = line

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace))
    if colour == 3:
        data += chunk(b"PLTE", bytes([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255]))
    return data + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def picture(x, y):
    return ((x * 37 + y * 11) % 256, (x * 5 + y * 53) % 256, (x * y) % 256, 255)


def cube_doc(texture=True, scale=(1.0, 2.0, 3.0), translation=(0.0, 1.0, 0.0)):
    """A unit cube (12 triangles) on a scaled node, so its world box is scale-sized. Returns (doc, binary)."""
    corners = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    indices = [i for a, b, c, d in faces for i in (a, b, c, a, c, d)]
    positions = b"".join(struct.pack("<3f", *c) for c in corners)
    index_bytes = struct.pack(f"<{len(indices)}H", *indices)
    binary = positions + index_bytes
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions), "target": 34962},
             {"buffer": 0, "byteOffset": len(positions), "byteLength": len(index_bytes), "target": 34963}]
    doc = {
        "asset": {"version": "2.0", "generator": "mstack test fixtures"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Box", "mesh": 0, "scale": list(scale), "translation": list(translation)}],
        "meshes": [{"name": "Box", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"name": "Paint", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.2, 0.2, 1.0]}}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3", "min": [-0.5, -0.5, -0.5], "max": [0.5, 0.5, 0.5]},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"}],
        "bufferViews": views,
    }
    if texture:
        image = png(8, 4, picture)
        binary = pad(binary, b"\x00")
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(image)})
        binary += image
        doc["images"] = [{"bufferView": 2, "mimeType": "image/png"}]
        doc["textures"] = [{"source": 0}]
        doc["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    doc["buffers"] = [{"byteLength": len(binary)}]
    return doc, binary


def rig_doc():
    """Hips -> Knee -> Foot_L chain standing on the floor, one skinned triangle, six clips with known answers."""
    binary, views, accessors = b"", [], []

    def add(data, component, kind, count, low=None, high=None):
        nonlocal binary
        binary = pad(binary, b"\x00")
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
        binary += data
        entry = {"bufferView": len(views) - 1, "componentType": component, "count": count, "type": kind}
        if low is not None:
            entry["min"], entry["max"] = low, high
        accessors.append(entry)
        return len(accessors) - 1

    def floats(rows):
        return b"".join(struct.pack(f"<{len(r)}f", *r) for r in rows)

    position = add(floats([(0, 0, 0), (0.1, 0, 0), (0, 1, 0)]), 5126, "VEC3", 3, [0, 0, 0], [0.1, 1, 0])
    joints = add(struct.pack("<12B", 2, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0), 5121, "VEC4", 3)
    weights = add(floats([(1, 0, 0, 0)] * 3), 5126, "VEC4", 3)

    def inverse_translation(y):
        return (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -y, 0, 1)

    bind = add(floats([inverse_translation(1.0), inverse_translation(0.5), inverse_translation(0.0)]), 5126, "MAT4", 3)

    def times(values):
        return add(floats([(v,) for v in values]), 5126, "SCALAR", len(values), [min(values)], [max(values)])

    def clip(name, node, path, keys, values, mode="LINEAR"):
        kind = "VEC4" if path == "rotation" else "VEC3"
        return {"name": name, "samplers": [{"input": times(keys), "output": add(floats(values), 5126, kind, len(values)), "interpolation": mode}],
                "channels": [{"sampler": 0, "target": {"node": node, "path": path}}]}

    half = math.sin(math.pi / 4)
    zero = (0.0, 0.0, 0.0)
    animations = [
        clip("planted", 1, "translation", [0, 0.5, 1], [(0, 1, 0), (0, 1, 0), (0, 1, 0)]),
        clip("slide", 1, "translation", [0, 0.5, 1], [(0, 1, 0), (0.3, 1, 0), (0.6, 1, 0)]),
        clip("sink", 1, "translation", [0, 1], [(0, 1, 0), (0, 0.9, 0)]),
        clip("swing", 1, "rotation", [0, 1], [(0, 0, 0, 1), (0, 0, half, half)]),
        clip("step", 3, "translation", [0, 0.5, 1], [(0, -0.5, 0), (0.2, -0.3, 0), (0.4, -0.5, 0)]),
        clip("grow", 1, "scale", [0, 1], [(1, 1, 1), (1.2, 1.2, 1.2)]),
        clip("spline", 3, "translation", [0, 1], [zero, (0, -0.5, 0), zero, zero, (0, -0.5, 0), zero], "CUBICSPLINE"),
    ]
    doc = {
        "asset": {"version": "2.0", "generator": "mstack test fixtures"},
        "scene": 0, "scenes": [{"nodes": [0, 4]}],
        "nodes": [
            {"name": "Armature", "children": [1]},
            {"name": "Hips", "translation": [0, 1, 0], "children": [2]},
            {"name": "Knee_L", "translation": [0, -0.5, 0], "children": [3]},
            {"name": "Foot_L", "translation": [0, -0.5, 0]},
            {"name": "Body", "mesh": 0, "skin": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": position, "JOINTS_0": joints, "WEIGHTS_0": weights}}]}],
        "skins": [{"name": "Rig", "joints": [1, 2, 3], "inverseBindMatrices": bind}],
        "animations": animations, "accessors": accessors, "bufferViews": views,
    }
    doc["buffers"] = [{"byteLength": len(binary)}]
    return doc, binary


def write_models(folder):
    """Write every model fixture into folder and return {name: path}."""
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    doc, binary = cube_doc()
    out = {}

    def save(name, data):
        path = folder / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        out[name] = path
        return path

    save("cube.glb", glb(doc, binary))
    plain, plain_bin = cube_doc(texture=False)
    save("cube_plain.glb", glb(plain, plain_bin))
    save("bad_length.glb", glb(doc, binary, declared_length=999999))
    save("bad_chunk.glb", glb(doc, binary, json_length=5000000))
    save("truncated.glb", glb(doc, binary)[:-40])
    broken = json.loads(json.dumps(doc))
    broken["accessors"][1]["count"] = 3600
    save("bad_accessor.glb", glb(broken, binary))
    no_asset = json.loads(json.dumps(doc))
    del no_asset["asset"]
    save("no_asset.glb", glb(no_asset, binary))
    dangling = json.loads(json.dumps(doc))
    dangling["nodes"][0]["mesh"] = 7
    dangling["meshes"][0]["primitives"][0]["material"] = 4
    save("bad_refs.glb", glb(dangling, binary))
    no_minmax = json.loads(json.dumps(doc))
    del no_minmax["accessors"][0]["min"], no_minmax["accessors"][0]["max"]
    save("no_minmax.glb", glb(no_minmax, binary))
    save("not_json.glb", struct.pack("<III", 0x46546C67, 2, 32) + struct.pack("<II", 12, CHUNK_JSON) + b"{not json!! ")
    save("error_page.glb", "<!doctype html><html><body><h1>403 Forbidden</h1></body></html>")
    save("api_reply.glb", '{"error": "quota exceeded", "status": 429}')
    save("empty.glb", b"")
    save("archive.glb", b"PK\x03\x04" + bytes(40))
    twice = json.loads(json.dumps(doc))
    twice["nodes"].append({"name": "Box2", "mesh": 0, "translation": [5, 0, 0]})
    twice["scenes"][0]["nodes"].append(1)
    save("two_boxes.glb", glb(twice, binary))
    external = json.loads(json.dumps(plain))
    external["buffers"][0]["uri"] = "cube_plain.bin"
    save("cube_plain.bin", plain_bin)
    save("cube_external.gltf", json.dumps(external))
    lost = json.loads(json.dumps(external))
    lost["buffers"][0]["uri"] = "gone.bin"
    save("cube_lost_buffer.gltf", json.dumps(lost))
    rig, rig_bin = rig_doc()
    save("rig.glb", glb(rig, rig_bin))
    return out


def write_images(folder):
    """Write PNG fixtures into folder and return {name: path}."""
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}

    def save(name, data):
        path = folder / name
        path.write_bytes(data)
        out[name] = path

    save("picture.png", png(64, 48, picture, filters=(0, 1, 2, 3, 4)))
    save("picture_rgb.png", png(64, 48, lambda x, y: picture(x, y)[:3], colour=2, filters=(4, 3, 1)))
    save("picture_shifted.png", png(64, 48, lambda x, y: picture(x + 9, y + 5), filters=(0, 1, 2, 3, 4)))
    save("picture_nudged.png", png(64, 48, lambda x, y: (min(picture(x, y)[0] + 1, 255), *picture(x, y)[1:]), filters=(2,)))
    save("black.png", png(64, 48, lambda x, y: (0, 0, 0, 255)))
    save("grey.png", png(64, 48, lambda x, y: (128,), colour=0))
    save("clear.png", png(64, 48, lambda x, y: (x * 4 % 256, y * 5 % 256, 9, 0)))
    save("dot.png", png(64, 48, lambda x, y: (255, 255, 255, 255) if (x, y) == (3, 3) else (20, 20, 30, 255)))
    save("palette.png", png(64, 48, lambda x, y: ((x // 8 + y // 8) % 4,), colour=3))
    save("grey_alpha.png", png(64, 48, lambda x, y: ((x * 4) % 256, 255), colour=4, filters=(1, 2)))
    save("deep.png", png(8, 8, lambda x, y: (0, x, 0, y, 0, 0, 255, 255), colour=6, depth=16))
    save("interlaced.png", png(8, 8, picture, interlace=1))
    save("small.png", png(32, 32, picture))
    save("not_a.png", b"GIF89a" + bytes(30))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=pathlib.Path, help="a new folder to write the fixtures into")
    args = parser.parse_args()
    if args.folder.exists():
        sys.exit(f"refusing: {args.folder} already exists")
    made = {**write_models(args.folder / "models"), **write_images(args.folder / "images")}
    print(f"wrote {len(made)} files under {args.folder}")
